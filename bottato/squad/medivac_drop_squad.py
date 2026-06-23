from __future__ import annotations

import math
from enum import Enum, auto
from typing import Dict, List, Optional

from cython_extensions.geometry import (
    cy_distance_to,
    cy_distance_to_squared,
    cy_towards,
)
from cython_extensions.units_utils import cy_closest_to
from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.log_helper import LogHelper
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.medivac_micro import MedivacMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.harass_squad import HarassSquad
from bottato.tactics import Tactics
from bottato.unit_reference_helper import UnitReferenceHelper
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

    MARINES_PER_DROP = 8
    # 8 marines x1 supply
    DROP_SUPPLY = 8
    MARINE_ATTACK_RANGE = 5.0

    def __init__(self, bot: BotAI, name: str, tactics: Tactics):
        super().__init__(bot, name, tactics)
        self.state: DropState = DropState.LOADING
        self.initial_marine_count: int = 0
        # clockwise=1, counter-clockwise=-1, keyed by medivac tag
        self.flank_direction: Dict[int, int] = {}
        self.marine_tags: List[int] = []
        self.medivac_micro: BaseUnitMicro = MicroFactory.get_unit_micro(UnitTypeId.MEDIVAC)
        self.marine_micro: BaseUnitMicro = MicroFactory.get_unit_micro(UnitTypeId.MARINE)
        
        self.enemy_corner = self._nearest_corner(self.bot.enemy_start_locations[0])

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
            area.x,
            area.y,
            area.right,
            area.top,
        )

    def _nearest_edge_point(self, pos: Point2) -> Point2:
        x_min, y_min, x_max, y_max = self._playable_rect()
        x_nearest = self._nearest_edge_x_coord(pos)
        y_nearest = self._nearest_edge_y_coord(pos)
        candidates = [
            Point2((x_nearest, max(y_min, min(y_max, pos.y)))),
            Point2((max(x_min, min(x_max, pos.x)), y_nearest)),
        ]
        return min(candidates, key=lambda p: p._distance_squared(pos))
    
    def _nearest_corner(self, pos: Point2) -> Point2:
        x_nearest = self._nearest_edge_x_coord(pos)
        y_nearest = self._nearest_edge_y_coord(pos)
        return Point2((x_nearest, y_nearest))
    
    def _nearest_edge_x_coord(self, pos: Point2) -> float:
        x_min, _, x_max, _ = self._playable_rect()
        return x_min if abs(pos.x - x_min) < abs(pos.x - x_max) else x_max
    
    def _nearest_edge_y_coord(self, pos: Point2) -> float:
        _, y_min, _, y_max = self._playable_rect()
        return y_min if abs(pos.y - y_min) < abs(pos.y - y_max) else y_max

    def _is_on_edge(self, pos: Point2) -> bool:
        x_min, y_min, x_max, y_max = self._playable_rect()
        return pos.x <= x_min + 3 or pos.x >= x_max - 3 or pos.y <= y_min + 3 or pos.y >= y_max - 3

    def _edge_waypoint_toward_enemy(self, pos: Point2) -> Point2:
        x_min, y_min, x_max, y_max = self._playable_rect()
        on_left = pos.x <= x_min + 3
        on_right = pos.x >= x_max - 3
        on_bottom = pos.y <= y_min + 3
        on_top = pos.y >= y_max - 3

        step = 15.0
        dx = self.enemy_corner.x - pos.x
        dy = self.enemy_corner.y - pos.y
        on_x_edge = on_left or on_right
        on_y_edge = on_bottom or on_top

        if on_x_edge and on_y_edge:
            # Corner: follow whichever axis has more distance left to reach the enemy corner
            if abs(dx) >= abs(dy):
                nx = pos.x + (step if dx > 0 else -step)
                return Point2((max(x_min, min(x_max, nx)), pos.y))
            else:
                ny = pos.y + (step if dy > 0 else -step)
                return Point2((pos.x, max(y_min, min(y_max, ny))))
        elif on_x_edge:
            ny = pos.y + (step if dy > 0 else -step)
            return Point2((pos.x, max(y_min, min(y_max, ny))))
        elif on_y_edge:
            nx = pos.x + (step if dx > 0 else -step)
            return Point2((max(x_min, min(x_max, nx)), pos.y))
        else:
            # Not on edge — go to nearest edge
            return self._nearest_edge_point(pos)

    def _nearby_enemy_military_supply(self, pos: Point2, radius: float = 15.0) -> float:
        total = 0.0
        for unit in self.bot.enemy_units:
            if unit.distance_to(pos) < radius and not UnitTypes.is_worker(unit):
                unit_info = UnitTypes.get_unit_info(unit.type_id)
                total += unit_info["supply"]
        # don't drop on a pf
        for structure in self.bot.enemy_structures.of_type(UnitTypeId.PLANETARYFORTRESS):
            if structure.distance_to(pos) < radius:
                total += 15  # planetary fortress supply
        return total

    def _nearby_friendly_military_supply(self, pos: Point2, radius: float = 15.0) -> float:
        total = 0.0
        for unit in self.bot.units:
            if unit.distance_to(pos) < radius and not UnitTypes.is_worker(unit):
                unit_info = UnitTypes.get_unit_info(unit.type_id)
                total += unit_info["supply"]
        # don't drop on a pf
        for structure in self.bot.enemy_structures.of_type(UnitTypeId.PLANETARYFORTRESS):
            if structure.distance_to(pos) < radius:
                total += 15  # planetary fortress supply
        return total

    def _get_flank_position(self, medivac: Unit, enemy_pos: Point2, radius: float = 14.0) -> Point2:
        tag = medivac.tag
        if tag not in self.flank_direction:
            self.flank_direction[tag] = 1  # clockwise
        direction = self.flank_direction[tag]

        if medivac.position == enemy_pos:
            return self.bot.start_location
        threat_to_unit_vector = (medivac.position - enemy_pos).normalized
        flipped = ((-threat_to_unit_vector.y, threat_to_unit_vector.x) if direction < 0 else
                   (threat_to_unit_vector.y, -threat_to_unit_vector.x))
        tangent_vector = Point2(flipped) * medivac.movement_speed
        flank_position = Point2(cy_towards(medivac.position + tangent_vector, enemy_pos, -1))

        x_min, y_min, x_max, y_max = self._playable_rect()
        if not (x_min <= flank_position.x <= x_max and y_min <= flank_position.y <= y_max):
            # Flip direction
            direction = -direction
            self.flank_direction[tag] = direction
            threat_to_unit_vector = (medivac.position - enemy_pos).normalized
            flipped = ((-threat_to_unit_vector.y, threat_to_unit_vector.x) if direction < 0 else
                    (threat_to_unit_vector.y, -threat_to_unit_vector.x))
            tangent_vector = Point2(flipped) * medivac.movement_speed
            flank_position = Point2(cy_towards(medivac.position + tangent_vector, enemy_pos, -1))

        return flank_position

    def _best_attack_target(self, medivac: Unit) -> Optional[Unit]:
        if self.bot.enemy_units.exclude_type([UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.CHANGELING,
                                              UnitTypeId.ADEPTPHASESHIFT, UnitTypeId.MULE]):
            return self.bot.enemy_units.closest_to(medivac.position)
        if self.bot.enemy_structures.exclude_type([UnitTypeId.REFINERY, UnitTypeId.EXTRACTOR, UnitTypeId.ASSIMILATOR,
                                                   UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORQUEEN, UnitTypeId.BUNKER,
                                                   UnitTypeId.PHOTONCANNON, UnitTypeId.SPORECRAWLER, UnitTypeId.SPINECRAWLER,
                                                   UnitTypeId.PLANETARYFORTRESS]):
            return self.bot.enemy_structures.closest_to(medivac.position)
        return None

    # Override harass from HarassSquad — completely different behaviour
    async def harass(self, intel: EnemyIntel):
        # Re-add any marines that were unloaded from the medivac back into self.units
        if self.marine_tags and len(self.marine_tags) > len(self.units) - 1:
            for marine in UnitReferenceHelper.get_updated_units_by_tag(self.marine_tags):
                self.recruit(marine)

        medivac = self.medivac_unit
        if not medivac:
            self.state = DropState.DISBANDING
            return

        # Check disband condition (1 marine killed)
        
        healthy_passenger_count = sum(1 for p in medivac.passengers if p.health_percentage > 0.5)
        healthy_ground_unit_count = sum(1 for m in self.units(UnitTypeId.MARINE) if m.health_percentage > 0.5)
        have_healthy_marines = healthy_passenger_count + healthy_ground_unit_count > 3
        if (
            self.state not in (DropState.LOADING, DropState.DISBANDING)
            and self.initial_marine_count > 0
            and (self._marines_killed(medivac) >= 1 or not have_healthy_marines or medivac.health_percentage < 0.5)
        ):
            self.state = DropState.DISBANDING

        if self.state == DropState.LOADING:
            await self._do_loading(medivac)
        elif self.state == DropState.FLYING_TO_EDGE:
            await self._do_flying_to_edge(medivac)
        elif self.state == DropState.FOLLOWING_EDGE:
            await self._do_following_edge(medivac)
        elif self.state == DropState.ATTACKING:
            await self._do_attacking(medivac)
        elif self.state == DropState.RETREATING:
            await self._do_retreating(medivac)
        elif self.state == DropState.FLANKING:
            await self._do_flanking(medivac)
        elif self.state == DropState.DISBANDING:
            await self._do_disbanding(medivac)

    async def _do_loading(self, medivac: Unit):
        """Load the marines."""
        # All loaded
        if self._passenger_marine_count(medivac) >= self.MARINES_PER_DROP:
            self.initial_marine_count = self.MARINES_PER_DROP
            self.state = DropState.FLYING_TO_EDGE
            LogHelper.add_log("medivac drop loading complete")
            await self._do_flying_to_edge(medivac)
            return

        if not self.marines:
            self.state = DropState.DISBANDING
            LogHelper.add_log("medivac drop disbanding, insufficient marines")
            await self._do_disbanding(medivac)
            return
        
        await self.load_marines()

    async def _do_flying_to_edge(self, medivac: Unit):
        """Fly to the nearest map edge."""
        edge_point = self._nearest_edge_point(medivac.position)
        if cy_distance_to_squared(medivac.position, edge_point) < 9:  # within 3 range
            self.state = DropState.FOLLOWING_EDGE
            LogHelper.add_log("medivac drop reached edge")
            await self._do_following_edge(medivac)
        else:
            await self.medivac_micro.harass(medivac, edge_point)

    async def _do_following_edge(self, medivac: Unit):
        """Follow map edge towards nearest enemy base."""
        # If close enough to enemy, transition to attack/flank decision
        if cy_distance_to(medivac.position, self.enemy_corner) < 20:
            target = self._best_attack_target(medivac)
            if target:
                if self._is_safe_to_unload(medivac):
                    self.state = DropState.ATTACKING
                    await self._do_attacking(medivac)
                else:
                    self.state = DropState.FLANKING
                    await self._do_flanking(medivac)
            else:
                # reached enemy corner but no targets
                self.state = DropState.DISBANDING
                await self._do_disbanding(medivac)
            return

        # Check for visible enemies
        nearby = self.bot.all_enemy_units.filter(
            lambda u: cy_distance_to_squared(u.position, medivac.position) < 400  # 20^2
                and (not u.is_structure or u.type_id in UnitTypes.ANTI_AIR_STRUCTURE_TYPES)
        )
        if nearby:
            target = self._best_attack_target(medivac)
            if target and self._is_safe_to_unload(medivac):
                self.state = DropState.ATTACKING
                await self._do_attacking(medivac)
            else:
                self.state = DropState.FLANKING
                await self._do_flanking(medivac)
            return

        if self._is_on_edge(medivac.position):
            waypoint = self._edge_waypoint_toward_enemy(medivac.position)
        else:
            waypoint = self._nearest_edge_point(medivac.position)

        await self.medivac_micro.harass(medivac, waypoint)

    def _is_safe_to_unload(self, medivac: Unit):
        nearby_friendly_supply = self._nearby_friendly_military_supply(medivac.position, radius=15)
        enemy_supply = self._nearby_enemy_military_supply(medivac.position, radius=15)
        return enemy_supply < self.DROP_SUPPLY + nearby_friendly_supply

    async def _do_attacking(self, medivac: Unit):
        """Move toward enemy and unload when in marine attack range."""
        target = self._best_attack_target(medivac)
        if not target:
            self.state = DropState.FOLLOWING_EDGE
            await self._do_following_edge(medivac)
            return

        # Re-evaluate — did the enemy supply grow?
        if not self._is_safe_to_unload(medivac):
            self.state = DropState.RETREATING
            await self._do_retreating(medivac)
            return

        # Check if anti-air structure blocks direct access
        aa_structures = self.bot.enemy_structures.filter(
            lambda s: s.is_ready
            and UnitTypes.air_range(s) > 0
            and s.position.distance_to(target.position) < 10
        )

        # Command unloaded marines to attack
        have_healthy_passengers = any(p.health_percentage > 0.5 for p in medivac.passengers)
        for marine in self.marines:
            if marine.health_percentage <= 0.3:
                marine.smart(medivac)
            else:
                await self.marine_micro.move(marine, target.position)

        if aa_structures:
            aa = aa_structures.closest_to(medivac.position)
            aa_range = UnitTypes.air_range(aa)
            aa_distance = cy_distance_to(aa.position, medivac.position)
            safe_distance = aa_range + aa.radius + medivac.radius + 2
            safe_pos = Point2(cy_towards(aa.position, medivac.position, safe_distance))
            if aa_distance < safe_distance:
                await self.medivac_micro.harass(medivac, safe_pos)
                return
            if cy_distance_to_squared(medivac.position, safe_pos) < 4 and have_healthy_passengers:
                medivac(AbilityId.UNLOADALLAT, medivac)
                return

        dist = medivac.position.distance_to(target.position)
        if dist <= self.MARINE_ATTACK_RANGE + 3 and have_healthy_passengers:
            medivac(AbilityId.UNLOADALLAT, medivac)
        else:
            await self.medivac_micro.harass(medivac, Point2(cy_towards(target.position, medivac.position, self.MARINE_ATTACK_RANGE)))

    async def _do_retreating(self, medivac: Unit):
        """Load any unloaded marines, then start flanking."""
        if await self.load_marines():
            # All loaded or dead — start flanking
            self.state = DropState.FLANKING
            await self._do_flanking(medivac)  # call without awaiting to set initial flank direction immediately

    async def _do_flanking(self, medivac: Unit):
        """Move clockwise or counter-clockwise around enemy to find better approach."""
        target = self._best_attack_target(medivac)
        if target and self._is_safe_to_unload(medivac):
            self.state = DropState.ATTACKING
            await self._do_attacking(medivac)
            return

        nearby = self.bot.all_enemy_units.filter(
            lambda u: cy_distance_to_squared(u.position, medivac.position) < 400  # 20^2
                and (not u.is_structure or u.type_id in UnitTypes.ANTI_AIR_STRUCTURE_TYPES)
                and not UnitTypes.is_worker(u)
        )
        if not nearby:
            self.state = DropState.FOLLOWING_EDGE
            await self._do_following_edge(medivac)
            return
        
        closest_enemy = cy_closest_to(medivac.position, nearby)
        flank_pos = self._get_flank_position(medivac, closest_enemy.position)
        await self.medivac_micro.harass(medivac, flank_pos)

    async def _do_disbanding(self, medivac: Unit):
        """Load remaining marines, fly toward base to be dissolved by Military."""
        if medivac.health_percentage < 0.25:
            medivac(AbilityId.UNLOADALL, medivac)
        elif medivac.health_percentage < 0.5:
            medivac.move(self.bot.start_location)
        elif await self.load_marines():
            # All marines aboard — head home
            medivac.move(self.bot.start_location)

    async def load_marines(self) -> bool:
        # load marines into transport, return True if all marines loaded or no medivac
        medivac = self.medivac_unit
        if not medivac:
            return True
        if not self.marines:
            return True
        # Save tags of visible marines before they enter cargo and disappear from all_units
        for marine in self.marines:
            if marine.tag not in self.marine_tags:
                self.marine_tags.append(marine.tag)
        nearest = self.marines.closest_to(medivac.position)
        medivac(AbilityId.LOAD, nearest)
        for marine in self.marines:
            if cy_distance_to_squared(marine.position, medivac.position) < 9:
                marine.smart(medivac)
            else:
                await self.marine_micro.harass(marine, medivac.position)
        return False

