from __future__ import annotations

import math
from enum import Enum, auto
from typing import Dict, Optional

from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.squad.harass_squad import HarassSquad
from bottato.squad.enemy_intel import EnemyIntel
from bottato.unit_types import UnitTypes


class DropState(Enum):
    LOADING = auto()
    FLYING_TO_EDGE = auto()
    FOLLOWING_EDGE = auto()
    ATTACKING = auto()
    RETREATING = auto()
    FLANKING = auto()
    DISBANDING = auto()


class MedivacDropSquad(HarassSquad):
    """Medivac drop harass: sneaks marines into enemy base via map edge."""

    MARINES_PER_DROP = 6
    # 6 marines x1 supply + 1 medivac x2 supply = 8
    DROP_SUPPLY = 8
    MARINE_ATTACK_RANGE = 5.0

    def __init__(self, bot: BotAI, name: str):
        super().__init__(bot, name)
        self.state: DropState = DropState.LOADING
        self.initial_marine_count: int = 0
        # clockwise=1, counter-clockwise=-1, keyed by medivac tag
        self.flank_direction: Dict[int, int] = {}

    def __repr__(self) -> str:
        return f"MedivacDropSquad({self.name},{len(self.units)},{self.state.name})"

    @property
    def medivac_unit(self) -> Optional[Unit]:
        medivacs = self.units.of_type(UnitTypeId.MEDIVAC)
        return medivacs.first if medivacs else None

    @property
    def marines(self) -> Units:
        return self.units.of_type(UnitTypeId.MARINE)

    @property
    def is_disbanding(self) -> bool:
        return self.state == DropState.DISBANDING

    def _passenger_marine_count(self, medivac: Unit) -> int:
        return sum(1 for p in medivac.passengers if p.type_id == UnitTypeId.MARINE)

    def _total_marine_count(self, medivac: Unit) -> int:
        return self.marines.amount + self._passenger_marine_count(medivac)

    def _marines_killed(self, medivac: Unit) -> int:
        if self.initial_marine_count == 0:
            return 0
        return self.initial_marine_count - self._total_marine_count(medivac)

    def _playable_rect(self):
        area = self.bot.game_info.playable_area
        return (
            area.x + 2,
            area.y + 2,
            area.x + area.width - 2,
            area.y + area.height - 2,
        )

    def _nearest_edge_point(self, pos: Point2) -> Point2:
        x_min, y_min, x_max, y_max = self._playable_rect()
        candidates = [
            Point2((x_min, max(y_min, min(y_max, pos.y)))),
            Point2((x_max, max(y_min, min(y_max, pos.y)))),
            Point2((max(x_min, min(x_max, pos.x)), y_min)),
            Point2((max(x_min, min(x_max, pos.x)), y_max)),
        ]
        return min(candidates, key=lambda p: p._distance_squared(pos))

    def _is_on_edge(self, pos: Point2) -> bool:
        x_min, y_min, x_max, y_max = self._playable_rect()
        return pos.x <= x_min + 3 or pos.x >= x_max - 3 or pos.y <= y_min + 3 or pos.y >= y_max - 3

    def _edge_waypoint_toward_enemy(self, pos: Point2, enemy_pos: Point2) -> Point2:
        x_min, y_min, x_max, y_max = self._playable_rect()
        on_left = pos.x <= x_min + 3
        on_right = pos.x >= x_max - 3
        on_bottom = pos.y <= y_min + 3
        on_top = pos.y >= y_max - 3

        step = 15.0
        if on_left or on_right:
            dy = enemy_pos.y - pos.y
            ny = pos.y + (step if dy > 0 else -step)
            return Point2((pos.x, max(y_min, min(y_max, ny))))
        elif on_bottom or on_top:
            dx = enemy_pos.x - pos.x
            nx = pos.x + (step if dx > 0 else -step)
            return Point2((max(x_min, min(x_max, nx)), pos.y))
        else:
            # Not on edge — go to nearest edge
            return self._nearest_edge_point(pos)

    def _nearby_enemy_military_supply(self, pos: Point2, radius: float = 15.0) -> float:
        total = 0.0
        for unit in self.bot.enemy_units:
            if unit.distance_to(pos) < radius and not UnitTypes.is_worker(unit.type_id):
                total += unit.supply_cost if hasattr(unit, 'supply_cost') else 1.0
        return total

    def _get_flank_position(self, medivac: Unit, enemy_pos: Point2, radius: float = 14.0) -> Point2:
        tag = medivac.tag
        if tag not in self.flank_direction:
            self.flank_direction[tag] = 1  # clockwise
        direction = self.flank_direction[tag]

        dx = medivac.position.x - enemy_pos.x
        dy = medivac.position.y - enemy_pos.y
        current_angle = math.atan2(dy, dx)
        step = math.pi / 4  # 45 degrees per flank step

        new_angle = current_angle + direction * step
        x_min, y_min, x_max, y_max = self._playable_rect()
        new_x = enemy_pos.x + radius * math.cos(new_angle)
        new_y = enemy_pos.y + radius * math.sin(new_angle)

        if not (x_min <= new_x <= x_max and y_min <= new_y <= y_max):
            # Flip direction
            self.flank_direction[tag] = -direction
            new_angle = current_angle - direction * step
            new_x = enemy_pos.x + radius * math.cos(new_angle)
            new_y = enemy_pos.y + radius * math.sin(new_angle)
            new_x = max(x_min, min(x_max, new_x))
            new_y = max(y_min, min(y_max, new_y))

        return Point2((new_x, new_y))

    def _best_attack_target(self, medivac: Unit) -> Optional[Unit]:
        if self.bot.enemy_units:
            return self.bot.enemy_units.closest_to(medivac.position)
        if self.bot.enemy_structures:
            return self.bot.enemy_structures.closest_to(medivac.position)
        return None

    # Override harass from HarassSquad — completely different behaviour
    async def harass(self, intel: EnemyIntel):
        if not self.units:
            return

        medivac = self.medivac_unit
        if not medivac:
            self.state = DropState.DISBANDING
            return

        # Check disband condition (3 marines killed)
        if (
            self.state not in (DropState.LOADING, DropState.DISBANDING)
            and self.initial_marine_count > 0
            and self._marines_killed(medivac) >= 3
        ):
            self.state = DropState.DISBANDING

        if self.state == DropState.LOADING:
            await self._do_loading(medivac)
        elif self.state == DropState.FLYING_TO_EDGE:
            await self._do_flying_to_edge(medivac)
        elif self.state == DropState.FOLLOWING_EDGE:
            await self._do_following_edge(medivac, intel)
        elif self.state == DropState.ATTACKING:
            await self._do_attacking(medivac)
        elif self.state == DropState.RETREATING:
            await self._do_retreating(medivac)
        elif self.state == DropState.FLANKING:
            await self._do_flanking(medivac, intel)
        elif self.state == DropState.DISBANDING:
            await self._do_disbanding(medivac)

    async def _do_loading(self, medivac: Unit):
        """Load the 6 healthiest (nearest if tied on health) marines."""
        marines = self.marines
        if not marines:
            return

        # All loaded
        if self._passenger_marine_count(medivac) >= self.MARINES_PER_DROP:
            self.initial_marine_count = self.MARINES_PER_DROP
            self.state = DropState.FLYING_TO_EDGE
            return

        # Find next marine to load: healthiest, tiebreak = nearest to medivac
        unloaded = [m for m in marines if m.cargo_size <= medivac.cargo_left]
        if not unloaded:
            return
        unloaded.sort(key=lambda m: (-m.health, m.distance_to(medivac)))
        medivac(AbilityId.LOAD_MEDIVAC, unloaded[0])

    async def _do_flying_to_edge(self, medivac: Unit):
        """Fly to the nearest map edge."""
        edge_point = self._nearest_edge_point(medivac.position)
        if medivac.position._distance_squared(edge_point) < 9:  # within 3 range
            self.state = DropState.FOLLOWING_EDGE
        else:
            medivac.move(edge_point)

    async def _do_following_edge(self, medivac: Unit, intel: EnemyIntel):
        """Follow map edge towards nearest enemy base."""
        enemy_pos = self.bot.enemy_start_locations[0]
        if self.bot.enemy_structures:
            enemy_pos = self.bot.enemy_structures.closest_to(medivac.position).position

        # If close enough to enemy, transition to attack/flank decision
        if medivac.position.distance_to(enemy_pos) < 20:
            await self._decide_action(medivac)
            return

        # Check for visible enemies
        nearby = self.bot.enemy_units.filter(
            lambda u: u.distance_to(medivac.position) < 20 and not UnitTypes.is_worker(u.type_id)
        )
        if nearby:
            await self._decide_action(medivac)
            return

        if self._is_on_edge(medivac.position):
            waypoint = self._edge_waypoint_toward_enemy(medivac.position, enemy_pos)
        else:
            waypoint = self._nearest_edge_point(medivac.position)

        medivac.move(waypoint)

    async def _decide_action(self, medivac: Unit):
        """Decide attack vs retreat based on nearby enemy military supply."""
        enemy_supply = self._nearby_enemy_military_supply(medivac.position, radius=15)
        if enemy_supply < self.DROP_SUPPLY:
            self.state = DropState.ATTACKING
        else:
            self.state = DropState.RETREATING

    async def _do_attacking(self, medivac: Unit):
        """Move toward enemy and unload when in marine attack range."""
        target = self._best_attack_target(medivac)
        if not target:
            self.state = DropState.FOLLOWING_EDGE
            return

        # Re-evaluate — did the enemy supply grow?
        enemy_supply = self._nearby_enemy_military_supply(medivac.position, radius=20)
        if enemy_supply >= self.DROP_SUPPLY:
            self.state = DropState.RETREATING
            return

        dist = medivac.position.distance_to(target.position)

        # Check if anti-air structure blocks direct access
        aa_structures = self.bot.enemy_structures.filter(
            lambda s: s.is_ready
            and UnitTypes.air_range(s) > 0
            and s.position.distance_to(target.position) < 10
        )

        if aa_structures:
            aa = aa_structures.closest_to(medivac.position)
            aa_range = UnitTypes.air_range(aa)
            # Drop just outside AA range
            dx = medivac.position.x - aa.position.x
            dy = medivac.position.y - aa.position.y
            dist_to_aa = math.hypot(dx, dy) or 1.0
            safe_x = aa.position.x + dx / dist_to_aa * (aa_range + 2)
            safe_y = aa.position.y + dy / dist_to_aa * (aa_range + 2)
            drop_pos = Point2((safe_x, safe_y))
            if medivac.position._distance_squared(drop_pos) < 4:
                medivac(AbilityId.UNLOADALLAT, medivac)
            else:
                medivac.move(drop_pos)
        elif dist <= self.MARINE_ATTACK_RANGE + 2 and medivac.passengers:
            medivac(AbilityId.UNLOADALLAT, medivac)
        else:
            medivac.move(target.position)

        # Command unloaded marines to attack
        for marine in self.marines:
            marine.attack(target.position)

    async def _do_retreating(self, medivac: Unit):
        """Load any unloaded marines, then start flanking."""
        for marine in self.marines:
            if medivac.cargo_left >= marine.cargo_size:
                medivac(AbilityId.LOAD_MEDIVAC, marine)
                return  # one load order per step

        if not self.marines:
            # All loaded or dead — start flanking
            self.state = DropState.FLANKING

    async def _do_flanking(self, medivac: Unit, intel: EnemyIntel):
        """Move clockwise or counter-clockwise around enemy to find better approach."""
        target = self._best_attack_target(medivac)
        if not target:
            self.state = DropState.FOLLOWING_EDGE
            return

        flank_pos = self._get_flank_position(medivac, target.position)
        if medivac.position._distance_squared(flank_pos) < 9:
            await self._decide_action(medivac)
        else:
            medivac.move(flank_pos)

    async def _do_disbanding(self, medivac: Unit):
        """Load remaining marines, fly toward base to be dissolved by Military."""
        for marine in self.marines:
            if medivac.cargo_left >= marine.cargo_size:
                medivac(AbilityId.LOAD_MEDIVAC, marine)
                return

        # All marines aboard — head home
        medivac.move(self.bot.start_location)
