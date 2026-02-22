from __future__ import annotations

# import math
from loguru import logger
from typing import Dict, List

from cython_extensions.general_utils import cy_in_pathing_grid_burny
from cython_extensions.geometry import (
    cy_distance_to,
    cy_distance_to_squared,
    cy_towards,
)
from cython_extensions.units_utils import cy_center, cy_closer_than, cy_closest_to
from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.enemy import Enemy
from bottato.enums import CustomEffectType, UnitMicroType
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.micro.custom_effect import CustomEffect
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.squad.enemy_intel import EnemyIntel
from bottato.unit_types import UnitTypes


class BaseUnitMicro(GeometryMixin):
    # move towards enemies if over attack_health and retreat if under retreat_health
    attack_health: float = 0.7
    retreat_health: float = 0.5
    # same as above but applied when harassing which prioritizes staying alive
    harass_attack_health: float = 0.8
    harass_retreat_health: float = 0.6
    time_in_frames_to_attack: float = 0.25 * 22.4
    scout_tags: set[int] = set()
    harass_tags: set[int] = set()
    healing_unit_tags: set[int] = set()
    tanks_being_retreated_to: Dict[int, float] = {}
    tanks_being_retreated_to_prev_frame: Dict[int, float] = {}
    harass_location_reached_tags: set[int] = set()
    repairer_tags: set[int] = set()
    repairer_tags_prev_frame: set[int] = set()
    repairers_by_target: Dict[int, List[int]] = {}  # target unit tag -> list of assigned repairer tags
    repairers_by_target_prev_frame: Dict[int, List[int]] = {}
    custom_effects_to_avoid: List[CustomEffect] = []  # position, time, radius, duration

    damaging_effects = [
        EffectId.PSISTORMPERSISTENT,
        # EffectId.GUARDIANSHIELDPERSISTENT,
        # EffectId.TEMPORALFIELDGROWINGBUBBLECREATEPERSISTENT,
        # EffectId.TEMPORALFIELDAFTERBUBBLECREATEPERSISTENT,
        EffectId.THERMALLANCESFORWARD,
        # EffectId.SCANNERSWEEP,
        EffectId.NUKEPERSISTENT,
        EffectId.LIBERATORTARGETMORPHDELAYPERSISTENT,
        EffectId.LIBERATORTARGETMORPHPERSISTENT,
        EffectId.BLINDINGCLOUDCP,
        EffectId.RAVAGERCORROSIVEBILECP,
        EffectId.LURKERMP,
        'KD8CHARGE',
    ]
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, intel: EnemyIntel):
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.map: Map = map
        self.intel: EnemyIntel = intel

    @staticmethod
    def reset_tag_sets():
        BaseUnitMicro.tanks_being_retreated_to_prev_frame = BaseUnitMicro.tanks_being_retreated_to
        BaseUnitMicro.tanks_being_retreated_to = {}
        BaseUnitMicro.repairer_tags_prev_frame = BaseUnitMicro.repairer_tags
        BaseUnitMicro.repairer_tags = set()
        BaseUnitMicro.repairers_by_target_prev_frame = BaseUnitMicro.repairers_by_target
        BaseUnitMicro.repairers_by_target = {}

    ###########################################################################
    # meta actions - used by non-micro classes to order units
    ###########################################################################        
    def get_override_target_for_repair(self, unit: Unit, target: Point2) -> Point2:
        if unit.tag in self.repairers_by_target_prev_frame:
            if unit.health_percentage > self.retreat_health and self.member_is_closer_than(unit, self.bot.enemy_units, 15):
                # don't move to repairer if in combat and healthy
                return target
            repairers = self.bot.units.filter(lambda u: u.tag in self.repairers_by_target_prev_frame[unit.tag])
            if repairers:
                repairer = cy_closest_to(unit.position, repairers)
                return repairer.position
        
        return target
    
    def add_repairer_for_unit(self, unit: Unit, repairer: Unit):
        self.repairers_by_target.setdefault(unit.tag, []).append(repairer.tag)

    @timed_async
    async def move(self, unit: Unit, target: Point2, force_move: bool = False, previous_position: Point2 | None = None) -> UnitMicroType:
        if unit.age > 0:
            LogHelper.write_log_to_db("stale unit micro", f"{unit}")
            return UnitMicroType.NONE
        if unit.tag in BaseUnitMicro.scout_tags:
            BaseUnitMicro.scout_tags.remove(unit.tag)
        elif unit.tag in BaseUnitMicro.harass_tags:
            BaseUnitMicro.harass_tags.remove(unit.tag)
        attack_health = self.attack_health
            
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE
        
        force_move = self._override_force_move(unit, force_move)

        target = self.get_override_target_for_repair(unit, target)
        action_taken: UnitMicroType = self._avoid_effects(unit, force_move)
        if action_taken == UnitMicroType.NONE:
            action_taken = await self._use_ability(unit, target, force_move=force_move)
        if action_taken == UnitMicroType.NONE:
            action_taken = self._move_to_repairer(unit)
        if action_taken == UnitMicroType.NONE:
            action_taken = self._attack_something(unit, health_threshold=attack_health, move_position=target, force_move=force_move)
        if action_taken == UnitMicroType.NONE:
            action_taken = await self._retreat(unit, health_threshold=self.retreat_health)
        if action_taken == UnitMicroType.NONE:
            action_taken = self._move_unit(unit, target, previous_position)
        return action_taken

    def _move_unit(self, unit: Unit, target: Point2, previous_position: Point2 | None = None) -> UnitMicroType:
        position_to_compare = target if unit.is_moving else unit.position
        if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1.5:
            unit.move(self.map.get_pathable_position(target, unit))
            return UnitMicroType.MOVE
        return UnitMicroType.MOVE
    
    def _harass_move_unit(self, unit: Unit, target: Point2, previous_position: Point2 | None = None) -> UnitMicroType:
        return self._move_unit(unit, target, previous_position)

    @timed_async
    async def harass(self, unit: Unit, target: Point2, force_move: bool = False, previous_position: Point2 | None = None) -> UnitMicroType:
        BaseUnitMicro.harass_tags.add(unit.tag)
        if unit.tag not in BaseUnitMicro.harass_location_reached_tags:
            if unit.position.manhattan_distance(target) < 10:
                BaseUnitMicro.harass_location_reached_tags.add(unit.tag)
        attack_health = self.attack_health
            
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE

        target = self.get_override_target_for_repair(unit, target)
        action_taken: UnitMicroType = self._avoid_effects(unit, force_move)
        if action_taken == UnitMicroType.NONE:
            action_taken = await self._use_ability(unit, target, force_move=force_move)
        if action_taken == UnitMicroType.NONE:
            action_taken = self._move_to_repairer(unit)
        if action_taken == UnitMicroType.NONE:
            action_taken = self._harass_attack_something(unit, health_threshold=attack_health, harass_location=target, force_move=force_move)
        if action_taken == UnitMicroType.NONE:
            action_taken = await self._harass_retreat(unit, health_threshold=self.retreat_health, harass_location=target)
        if action_taken == UnitMicroType.NONE:
            action_taken = self._harass_move_unit(unit, target, previous_position)
        return action_taken

    @timed_async
    async def scout(self, unit: Unit, scouting_location: Point2) -> UnitMicroType:
        BaseUnitMicro.scout_tags.add(unit.tag)
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE
        logger.debug(f"scout {unit} health {unit.health}/{unit.health_max} ({unit.health_percentage}) health")

        scouting_location = self.get_override_target_for_repair(unit, scouting_location)
        action_taken: UnitMicroType = self._avoid_effects(unit, False)
        if action_taken == UnitMicroType.NONE:
            action_taken = await self._retreat(unit, health_threshold=0.95)
        if action_taken == UnitMicroType.NONE:
            if unit.type_id == UnitTypeId.VIKINGFIGHTER:
                action_taken = self._attack_something(unit, health_threshold=1.0, move_position=scouting_location)
        if action_taken == UnitMicroType.NONE:
            logger.debug(f"scout {unit} moving to updated assignment {scouting_location}")
            unit.move(self.map.get_pathable_position(scouting_location, unit))
            action_taken = UnitMicroType.MOVE
        return action_taken

    @timed_async
    async def repair(self, unit: Unit, target: Unit) -> UnitMicroType:
        BaseUnitMicro.repairer_tags.add(unit.tag)
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE
        distance_sq = unit.distance_to_squared(target)
        self.add_repairer_for_unit(target, unit)
        action_taken: UnitMicroType = self._avoid_effects(unit, force_move=False)
        if action_taken == UnitMicroType.NONE:
            if target.type_id in (UnitTypeId.BUNKER, UnitTypeId.PLANETARYFORTRESS, UnitTypeId.MISSILETURRET, UnitTypeId.SIEGETANKSIEGED) \
                    and (distance_sq < 25 or distance_sq < self.closest_distance_squared(unit, self.bot.enemy_units)):
                # repair defensive structures regardless of risk
                unit.repair(target)
                action_taken = UnitMicroType.REPAIR
        if action_taken == UnitMicroType.NONE:
            if self.bot.time < 360 and cy_distance_to_squared(target.position, self.bot.main_base_ramp.top_center) < 25:
                # keep ramp wall repaired early game
                unit.repair(target)
                action_taken = UnitMicroType.REPAIR
        if action_taken == UnitMicroType.NONE:
            if self._retreat_to_better_unit(unit, can_attack=True):
                action_taken = UnitMicroType.RETREAT
        if action_taken == UnitMicroType.NONE:
            action_taken = await self._retreat(unit, health_threshold=0.25)
        if action_taken == UnitMicroType.NONE:
            if not target.is_structure and cy_distance_to(unit.position, target.position) > unit.radius + target.radius + 0.5:
                # sometimes they get in a weird state where they run from the target
                unit.move(target.position)
                action_taken = UnitMicroType.MOVE
            else:
                unit.repair(target)
                action_taken = UnitMicroType.REPAIR
        return action_taken

    ###########################################################################
    # main actions - iterated through by meta actions
    ###########################################################################
    fixed_radius: Dict[EffectId | str, float] = {
        EffectId.PSISTORMPERSISTENT: 2,
        EffectId.GUARDIANSHIELDPERSISTENT: 4.5,
        EffectId.SCANNERSWEEP: 13,
    }
    @staticmethod
    def add_custom_effect(type: CustomEffectType, position: Unit | Point2, radius: float, start_time: float, duration: float):
        for effect in BaseUnitMicro.custom_effects_to_avoid:
            if effect.position.position == position.position and effect.radius == radius:
                effect.start_time = start_time
                # don't add duplicates
                return
        BaseUnitMicro.custom_effects_to_avoid.append(CustomEffect(type, position, radius, start_time, duration))

    @timed
    def _avoid_effects(self, unit: Unit, force_move: bool) -> UnitMicroType:
        # avoid damaging effects
        effects_to_avoid = []
        for effect in self.bot.state.effects:
            if effect.id not in self.damaging_effects:
                continue
            if effect.id == EffectId.RAVAGERCORROSIVEBILECP:
                for position in effect.positions:
                    # bile lands a second after effect disappears so replace with custom effect
                    self.add_custom_effect(CustomEffectType.ENEMY_EFFECT,
                                           position=position,
                                           radius=effect.radius,
                                           start_time=self.bot.time,
                                           duration=1.0)
            if effect.id in (EffectId.LIBERATORTARGETMORPHDELAYPERSISTENT, EffectId.LIBERATORTARGETMORPHPERSISTENT):
                if effect.is_mine or unit.is_flying:
                    continue
            effect_radius = self.fixed_radius.get(effect.id, effect.radius)
            safe_distance = (effect_radius + unit.radius + 1.5) ** 2
            for position in effect.positions:
                if unit.position._distance_squared(position) < safe_distance:
                    effects_to_avoid.append(position)
        i = len(self.custom_effects_to_avoid) - 1
        while i >= 0:
            effect = self.custom_effects_to_avoid[i]
            effect_position = effect.position.position
            if self.bot.time - effect.start_time > effect.duration:
                self.custom_effects_to_avoid.pop(i)
            else:
                safe_distance = (effect.radius + unit.radius + 1.5) ** 2
                unit_distance = unit.position._distance_squared(effect_position)
                if unit_distance < safe_distance:
                    effects_to_avoid.append(effect_position)
            i -= 1
        if effects_to_avoid:
            number_of_effects = len(effects_to_avoid)
            if number_of_effects == 1:
                # move directly away from effect
                if unit.position == effects_to_avoid[0]:
                    new_position = Point2(cy_towards(unit.position, self.bot.start_location, 2))
                else:
                    new_position = Point2(cy_towards(unit.position, effects_to_avoid[0], -2))
                unit.move(new_position)
                return UnitMicroType.AVOID_EFFECTS
            average_x = sum(p.x for p in effects_to_avoid) / number_of_effects
            average_y = sum(p.y for p in effects_to_avoid) / number_of_effects
            average_position = Point2((average_x, average_y))
            # move out of effect radius
            new_position = Point2(cy_towards(unit.position, average_position, -2))
            unit.move(new_position)
            return UnitMicroType.AVOID_EFFECTS
        return UnitMicroType.NONE

    last_targets_update_time: float = 0.0
    valid_targets: Units | None = None
    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, force_move: bool = False) -> UnitMicroType:
        return UnitMicroType.NONE
    
    @timed
    def _move_to_repairer(self, unit: Unit) -> UnitMicroType:
        if unit.tag in BaseUnitMicro.repairers_by_target_prev_frame and unit.health_percentage < 1.0:
            repairer_tags = BaseUnitMicro.repairers_by_target_prev_frame[unit.tag]
            repairers = self.bot.workers.filter(lambda w: w.tag in repairer_tags)
            closest_repairer = cy_closest_to(unit.position, repairers) if repairers else None
            if closest_repairer and 1 < closest_repairer.distance_to_squared(unit) < 16:
                unit.move(closest_repairer)
                return UnitMicroType.MOVE
        return UnitMicroType.NONE

    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, move_position: Point2, force_move: bool = False) -> UnitMicroType:
        # attack best target in range or move towards best target if none in range
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.ATTACK

        # below retreat_health: do nothing
        if unit.health_percentage < self.retreat_health:
            return UnitMicroType.NONE

        if self.last_targets_update_time != self.bot.time:
            self.last_targets_update_time = self.bot.time
            self.valid_targets = self.bot.enemy_units.filter(
                lambda u: UnitTypes.can_be_attacked(u, self.bot, self.enemy.get_recent_enemies()) and u.armor < 10 and BuffId.NEURALPARASITE not in u.buffs
                ) + self.bot.enemy_structures

        if not self.valid_targets:
            return UnitMicroType.NONE
        nearby_enemies = Units(sorted(cy_closer_than(self.valid_targets, 20, unit.position), key=lambda u: u.health + u.shield), bot_object=self.bot)
        if not nearby_enemies:
            return UnitMicroType.NONE
        
        # attack enemy in range
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if can_attack:
            bonus_distance = -2 if unit.health_percentage < health_threshold else -0.5
            if UnitTypes.range(unit) < 1:
                bonus_distance = 1
            micro_taken = self._kite(unit, nearby_enemies, bonus_distance, force_move=force_move)
            if micro_taken != UnitMicroType.NONE:
                return micro_taken
            # attack_target = self._get_attack_target(unit, nearby_enemies, bonus_distance)
            # if attack_target:
            #     self._kite(unit, nearby_enemies)
            #     return UnitMicroType.ATTACK
        
        # retreat towards better counter for threats
        if self._retreat_to_better_unit(unit, can_attack):
            return UnitMicroType.RETREAT

        if force_move:
            return UnitMicroType.NONE

        # below attack_health: if threats and no target in range, do nothing (retreat)
        if unit.health_percentage < health_threshold:
            if self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6, first_only=True):
                return UnitMicroType.NONE

        # venture out a bit further to attack
        if can_attack:
            if move_position is not None and move_position.manhattan_distance(unit.position) < 20:
                micro_taken = self._kite(unit, nearby_enemies, 5)
                if micro_taken != UnitMicroType.NONE:
                    return micro_taken
        elif self.valid_targets:
            return self._kite(unit, self.valid_targets)

        return UnitMicroType.NONE
    
    @timed
    def _harass_attack_something(self, unit: Unit, health_threshold: float, harass_location: Point2, force_move: bool = False) -> UnitMicroType:
        return self._attack_something(unit, health_threshold, harass_location, force_move)

    @timed_async
    async def _retreat(self, unit: Unit, health_threshold: float) -> UnitMicroType:
        # below retreat_health: always retreat
        # below attack_health: retreat if threats
        # above attack_health: do nothing
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE
        
        threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=4)
        is_below_attack_health = unit.health_percentage < self.attack_health
        is_below_retreat_health = unit.health_percentage < health_threshold
        if not is_below_attack_health and threats:
            if not unit.health_max:
                # rare weirdness
                return UnitMicroType.NONE
            attack_threshold = unit.health_max * self.attack_health
            current_health = unit.health
            for threat in threats:
                current_health -= threat.calculate_damage_vs_target(unit)[0]
                if current_health < attack_threshold:
                    is_below_attack_health = True
                    break

        # above attack_health: do nothing
        if not is_below_attack_health:
            return UnitMicroType.NONE

        # below attack_health: retreat if threats
        # below retreat_health: always retreat
        if threats or is_below_retreat_health:
            retreat_position = self._get_retreat_destination(unit, threats)
            if unit.is_constructing_scv:
                unit(AbilityId.HALT)
            elif isinstance(retreat_position, Unit) and retreat_position.type_id == UnitTypeId.SCV and unit.type_id == UnitTypeId.SCV and retreat_position.health_percentage < 1.0:
                unit.repair(retreat_position)
            else:
                unit.move(retreat_position)
            return UnitMicroType.RETREAT

        return UnitMicroType.NONE
    
    @timed_async
    async def _harass_retreat(self, unit: Unit, health_threshold: float, harass_location: Point2) -> UnitMicroType:
        return await self._retreat(unit, health_threshold)

    ###########################################################################
    # utility behaviors - used by main actions
    ###########################################################################
    def _override_force_move(self, unit: Unit, force_move: bool) -> bool:
        if not force_move:
            return force_move
        if unit.type_id in (UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.MEDIVAC):
            if cy_closer_than(self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED), 15, unit.position):
                # don't force move if there are sieged tanks to defend
                return False
        return force_move

    @timed
    def _get_attack_target(self, unit: Unit, nearby_enemies: Units, bonus_distance: float = 0, require_in_range_target: bool = False) -> Unit | None:
        if not nearby_enemies:
            return None
        closest_target = cy_closest_to(unit.position, nearby_enemies)
        closest_distance = max(cy_distance_to(unit.position, closest_target.position), UnitTypes.range(unit))
        # look 3 beyond closest enemy for priority targets
        almost_closest_enemies = Units(cy_closer_than(nearby_enemies, closest_distance + 3, unit.position), bot_object=self.bot)
        priority_targets = almost_closest_enemies.filter(lambda u: u.type_id in UnitTypes.get_priority_target_types(unit))
        if priority_targets:
            in_range = self.enemy.in_attack_range(unit, priority_targets, bonus_distance, first_only=True)
            if in_range:
                return in_range.first
        # for non-priority targets, only look 1 distance beyond closest enemy
        almost_closest_enemies = Units(cy_closer_than(almost_closest_enemies, closest_distance + 1, unit.position), bot_object=self.bot)
        offensive_targets = almost_closest_enemies.filter(lambda u: UnitTypes.can_attack(u))
        if offensive_targets:
            threat_in_range = self.enemy.threat_in_attack_range(unit, offensive_targets, bonus_distance, first_only=True)
            if threat_in_range:
                return threat_in_range.first
            in_range = self.enemy.in_attack_range(unit, offensive_targets, bonus_distance, first_only=True)
            if in_range:
                return in_range.first
        passive_targets = almost_closest_enemies.filter(lambda u: not UnitTypes.can_attack(u))
        if passive_targets:
            in_range = self.enemy.in_attack_range(unit, passive_targets, bonus_distance, first_only=True)
            if in_range:
                return in_range.first
        # nothing in range, attack closest
        return None if require_in_range_target else closest_target
            
    def _stay_at_max_range(self, unit: Unit, targets: Units, buffer: float = 0.5, queue: bool = False) -> UnitMicroType:
        if not targets:
            return UnitMicroType.NONE
        if self.bot.time < 300 and unit.position.manhattan_distance(self.bot.main_base_ramp.top_center) < 10:
            if self.bot.get_terrain_height(unit) == self.bot.get_terrain_height(self.bot.start_location):
                # don't kite away from ramp wall early game
                return UnitMicroType.NONE
        if not targets:
            return UnitMicroType.NONE
        nearest_target = self.closest_unit_to_unit(unit, targets)
        # don't keep distance from structures since it prevents units in back from attacking
        # except for zerg structures that spawn broodlings when they die
        is_nonthreat_structure = nearest_target.is_structure \
            and nearest_target.type_id not in UnitTypes.OFFENSIVE_STRUCTURE_TYPES \
            and (nearest_target.race != Race.Zerg or nearest_target.type_id in UnitTypes.ZERG_STRUCTURES_THAT_DONT_SPAWN_BROODLINGS)
        is_passive_unit = not nearest_target.is_structure and not UnitTypes.can_attack(nearest_target)
        if is_passive_unit or is_nonthreat_structure:
            # nearest target isn't a threat, check for nearby threats before closing
            threats = targets.filter(lambda t: UnitTypes.can_attack_target(t, unit))
            if not threats:
                unit.move(self.map.get_pathable_position(nearest_target.position, unit), queue=queue)
                return UnitMicroType.MOVE
            nearest_target = self.closest_unit_to_unit(unit, threats)
        # move away if weapon on cooldown
        if not unit.is_flying:
            nearest_sieged_tank = None
            if nearest_target.type_id == UnitTypeId.SIEGETANKSIEGED:
                nearest_sieged_tank = nearest_target
            else:
                enemy_tanks = targets.of_type(UnitTypeId.SIEGETANKSIEGED)
                if enemy_tanks:
                    nearest_sieged_tank = self.closest_unit_to_unit(unit, enemy_tanks)

            if nearest_sieged_tank:
                distance_to_tank = self.distance(unit, nearest_sieged_tank)
                if distance_to_tank < 8:
                    # dive on sieged tanks
                    attack_range = 0
                    target_position = Point2(cy_towards(nearest_sieged_tank.position, unit.position, attack_range))
                    return self._move_to_pathable_position(unit, target_position, queue=queue)
                if distance_to_tank < 15:
                    attack_range = 14
                    target_position = Point2(cy_towards(nearest_sieged_tank.position, unit.position, attack_range))
                    return self._move_to_pathable_position(unit, target_position, queue=queue)

        attack_range = UnitTypes.range_vs_target(unit, nearest_target)
        future_enemy_position = Point2(cy_center(targets))
        target_position = Point2(cy_towards(future_enemy_position, unit.position, attack_range + unit.radius + nearest_target.radius + buffer))
        return self._move_to_pathable_position(unit, target_position, queue=queue)

    weapon_speed_vs_target_cache: dict[UnitTypeId, dict[UnitTypeId, float]] = {}

    def _kite(self, unit: Unit, targets: Units, bonus_distance: float = 0, force_move: bool = False) -> UnitMicroType:
        targets_to_avoid = Units([], bot_object=self.bot)
        workers_to_avoid = Units([], bot_object=self.bot)
        distance_to_advance: float = float('inf')
        can_be_attacked = UnitTypes.can_be_attacked(unit, self.bot, self.bot.enemy_units)
        can_outrun = True
        can_attack = unit.weapon_cooldown < self.time_in_frames_to_attack
        if can_be_attacked:
            for target in targets:
                if target.health == 0:
                    # cloaked, can't attack
                    continue
                attack_range = UnitTypes.range_vs_target(unit, target)
                target_range = UnitTypes.range_vs_target(target, unit)
                target_distance = self.distance(unit, target, self.enemy.predicted_positions) - target.radius - unit.radius
                if can_attack and target_distance <= attack_range and target.health + target.shield <= unit.calculate_damage_vs_target(target)[0]:
                    # secure kills on units that
                    unit.attack(target)
                    return UnitMicroType.ATTACK
                if target_range == 0:
                    if target.is_structure and target.race == Race.Zerg \
                            and target.type_id not in UnitTypes.ZERG_STRUCTURES_THAT_DONT_SPAWN_BROODLINGS:
                        # keep distance from zerg structures that spawn broodlings on death
                        desired_distance = attack_range
                        excess_distance = target_distance - desired_distance
                        if excess_distance < distance_to_advance:
                            distance_to_advance = excess_distance
                        if excess_distance < 0:
                            targets_to_avoid.append(target)
                    continue
                desired_distance = 0
                if target.type_id in UnitTypes.WORKER_TYPES:
                    desired_distance = target_range + 2.0
                else:
                    desired_distance = min(attack_range - 0.1, max(attack_range - 1.0, target_range + 0.5))
                excess_distance = target_distance - desired_distance
                if excess_distance < distance_to_advance:
                    distance_to_advance = excess_distance
                if excess_distance < 0:
                    can_outrun = can_outrun and (unit.movement_speed >= target.movement_speed or target_range == 0)
                    if target.type_id in UnitTypes.WORKER_TYPES:
                        workers_to_avoid.append(target)
                    else:
                        targets_to_avoid.append(target)
        
        target = None
        should_run = workers_to_avoid or targets_to_avoid and can_outrun
        # find a target if we can attack now or if we don't need to run
        if can_attack or not should_run:
            targets.sort(key=lambda t: t.health + t.shield)
            target = self._get_attack_target(unit, targets, bonus_distance, require_in_range_target=force_move)

        if can_attack and target:
            self._attack(unit, target)
            return UnitMicroType.ATTACK

        if can_outrun and targets_to_avoid:
            if self._stay_at_max_range(unit, targets_to_avoid) == UnitMicroType.NONE:
                unit.move(self._get_retreat_destination(unit, targets_to_avoid))
            return UnitMicroType.RETREAT
        if workers_to_avoid:
            # stay at minimum distance from workers instead of max attack range
            nearest_worker = self.closest_unit_to_unit(unit, workers_to_avoid)
            target_position = Point2(cy_towards(Point2(cy_center(workers_to_avoid)), unit.position, 3.0 + unit.radius + nearest_worker.radius))
            if self._move_to_pathable_position(unit, target_position) == UnitMicroType.NONE:
                unit.move(self._get_retreat_destination(unit, workers_to_avoid))
            return UnitMicroType.RETREAT

        if target:
            unit.move(unit.position.towards(target.position, distance_to_advance))
            return UnitMicroType.MOVE
        return UnitMicroType.NONE
    
    def _attack(self, unit: Unit, target: Unit) -> bool:
        if target.type_id == UnitTypeId.INTERCEPTOR:
            # interceptors can't be targeted directly
            unit.attack(target.position)
        elif target.age > 0:
            unit.move(self.map.get_pathable_position(self.enemy.predicted_positions[target.tag], unit))
        else:
            unit.attack(target)
        return True
    
    def _move_to_pathable_position(self, unit: Unit, position: Point2, queue: bool = False) -> UnitMicroType:
        if unit.is_flying and self.bot.in_map_bounds(position) or cy_in_pathing_grid_burny(self.bot.game_info.pathing_grid.data_numpy, position):
            unit.move(self.map.get_pathable_position(position, unit), queue=queue)
            return UnitMicroType.MOVE
        return UnitMicroType.NONE
            
    @timed
    def _get_retreat_destination(self, unit: Unit, threats: Units | None = None) -> Point2 | Unit:
        if threats is None:
            threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=2)
        else:
            threats = self.enemy.threats_to(unit, threats, attack_range_buffer=2)
        ultimate_destination: Point2 | Unit | None = None
        if unit.is_mechanical:
            if not threats or not threats.filter(lambda t: t.can_attack):
                repairer: Unit | None = None
                if unit.tag in self.repairers_by_target_prev_frame:
                    try:
                        repairers: Units = self.bot.units.filter(lambda w: w.tag in BaseUnitMicro.repairers_by_target_prev_frame[unit.tag])
                        if repairers:
                            repairer = cy_closest_to(unit.position, repairers)
                            ultimate_destination = repairer
                    except KeyError:
                        pass
                if repairer is None:
                    repairers: Units = self.bot.workers.filter(lambda w: w.tag in BaseUnitMicro.repairer_tags.union(BaseUnitMicro.repairer_tags_prev_frame))
                    if not repairers:
                        repairers = self.bot.workers.filter(lambda w: w.tag not in BaseUnitMicro.scout_tags)
                    if repairers and unit.type_id == UnitTypeId.SCV:
                        repairers = repairers.filter(lambda worker: worker.tag != unit.tag)
                    if repairers:
                        closest_repairer = cy_closest_to(unit.position, repairers)
                        if closest_repairer.position.manhattan_distance(unit.position) < 1:
                            ultimate_destination = unit
                        else:
                            ultimate_destination = closest_repairer
        else:
            medivacs = self.bot.units.of_type(UnitTypeId.MEDIVAC)
            if medivacs:
                ultimate_destination = cy_closest_to(unit.position, medivacs)
        if ultimate_destination is None:
            bunkers = self.bot.structures.of_type(UnitTypeId.BUNKER)
            if bunkers:
                away_from_position = Point2(cy_center(threats)) if threats else self.bot.game_info.map_center
                ultimate_destination = Point2(cy_towards(cy_closest_to(unit.position, bunkers).position, away_from_position, -4))
        
        if not ultimate_destination:
            ultimate_destination = self.bot.game_info.player_start_location
        
        if not threats:
            if isinstance(ultimate_destination, Unit):
                return ultimate_destination
            return self.map.get_pathable_position(ultimate_destination, unit)

        threat_center = Point2(cy_center(threats))
        closest_threat_to_destination = cy_closest_to(ultimate_destination.position, threats)
        if unit.position == threat_center or \
            cy_distance_to(unit.position, ultimate_destination.position) < cy_distance_to(closest_threat_to_destination.position, ultimate_destination.position) - 2:
            return self.map.get_pathable_position(ultimate_destination.position, unit)

        retreat_vector = GeometryMixin.get_vector_towards_biggest_gap(unit.position, [threat.position for threat in threats])
        retreat_distance = 10 if unit.is_flying else 5
        retreat_position = Point2(cy_towards(unit.position, unit.position + retreat_vector, retreat_distance))
        if unit.is_flying:
            retreat_position = self.map.clamp_position_to_map_bounds(retreat_position, unit.position, self.bot)
            return self.map.get_pathable_position(Point2(cy_towards(unit.position, retreat_position, 2)), unit)
        if self._position_is_pathable(unit, retreat_position):
            return self.map.get_pathable_position(Point2(cy_towards(unit.position, retreat_position, 2)), unit)

        circle_around_position = self.get_circle_around_position(unit, closest_threat_to_destination.position, ultimate_destination.position)
        return circle_around_position
    
    def _position_is_pathable(self, unit: Unit, position: Point2) -> bool:
        if unit.is_flying and self.bot.in_map_bounds(position) or cy_in_pathing_grid_burny(self.bot.game_info.pathing_grid.data_numpy, position):
            return True
        return False

    @timed
    def _retreat_to_medivac(self, unit: Unit) -> UnitMicroType:
        medivacs = self.bot.units.filter(lambda unit: unit.type_id == UnitTypeId.MEDIVAC and unit.energy > 5 and unit.cargo_used == 0)
        if medivacs:
            nearest_medivac = cy_closest_to(unit.position, medivacs)
            if unit.distance_to_squared(nearest_medivac) > 16:
                unit.move(nearest_medivac)
            else:
                unit.move(self._get_retreat_destination(unit,self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=4)))
            logger.debug(f"{unit} marine retreating to heal at {nearest_medivac} hp {unit.health_percentage}")
            self.healing_unit_tags.add(unit.tag)
        else:
            return UnitMicroType.NONE
        return UnitMicroType.RETREAT

    @timed
    def _retreat_to_better_unit(self, unit: Unit, can_attack: bool) -> bool:
        # retreat toward a unit that is better able to deal with whatever is threatening this unit.
        if not UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_recent_enemies()):
            return False

        if unit.health_percentage >= 0.9:
            injured_friendlies = self.bot.units.filter(lambda u: u.health_percentage < 0.9 and u.type_id in (UnitTypeId.MARINE, UnitTypeId.MARAUDER))
            # poke out at full health to lure enemy. only go if no nearby units are injured to promote grouping up
            if not self.member_is_closer_than(unit, injured_friendlies, 5):
                return False

        threats = self.enemy.threats_to_friendly_unit(unit, 1)
        if not threats:
            return False
        closest_threat = sorted(threats, key=lambda t: self.distance_squared(t, unit) - self.enemy.get_attack_range_with_buffer_squared(t, unit, 0))[0]
        closest_threat_distance_sq = self.distance_squared(closest_threat, unit)
        if closest_threat_distance_sq > 225:
            return False
        if closest_threat.type_id == UnitTypeId.SIEGETANKSIEGED and closest_threat_distance_sq < 49:
            # if enemy tank is close, dive on it instead of retreating
            return False

        type_to_retreat_to = UnitTypeId.SIEGETANKSIEGED
        if closest_threat.is_flying:
            if unit.type_id == UnitTypeId.VIKINGFIGHTER:
                type_to_retreat_to = UnitTypeId.MARINE
            else:
                type_to_retreat_to = UnitTypeId.VIKINGFIGHTER
        units_to_retreat_to = self.bot.units.of_type(type_to_retreat_to)
        if not units_to_retreat_to and type_to_retreat_to == UnitTypeId.SIEGETANKSIEGED:
            units_to_retreat_to = self.bot.units.of_type(UnitTypeId.SIEGETANK)
        if not units_to_retreat_to:
            return False

        nearest_unit_to_retreat_to = cy_closest_to(unit.position, units_to_retreat_to)
        ally_to_enemy_distance_sq = self.distance_squared(nearest_unit_to_retreat_to, closest_threat)

        if ally_to_enemy_distance_sq < 900 and ally_to_enemy_distance_sq > self.enemy.get_attack_range_with_buffer_squared(nearest_unit_to_retreat_to, closest_threat, 0):
            optimal_distance = UnitTypes.range_vs_target(nearest_unit_to_retreat_to, closest_threat) - UnitTypes.range_vs_target(closest_threat, nearest_unit_to_retreat_to) - unit.radius + nearest_unit_to_retreat_to.radius - 2.0
            unit.move(Point2(cy_towards(nearest_unit_to_retreat_to.position, unit.position, optimal_distance)))
            if nearest_unit_to_retreat_to.type_id in (UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED) \
                and (nearest_unit_to_retreat_to.tag not in BaseUnitMicro.tanks_being_retreated_to \
                     or ally_to_enemy_distance_sq < BaseUnitMicro.tanks_being_retreated_to[nearest_unit_to_retreat_to.tag]):
                BaseUnitMicro.tanks_being_retreated_to[nearest_unit_to_retreat_to.tag] = ally_to_enemy_distance_sq
            return True
        elif not can_attack and ally_to_enemy_distance_sq < self.distance_squared(unit, closest_threat) * 0.3:
            # defend tank if it's closer to enemy than unit
            unit.move(Point2(cy_towards(nearest_unit_to_retreat_to.position, closest_threat.position, 3)))
            if nearest_unit_to_retreat_to.tag not in BaseUnitMicro.tanks_being_retreated_to or ally_to_enemy_distance_sq < BaseUnitMicro.tanks_being_retreated_to[nearest_unit_to_retreat_to.tag]:
                BaseUnitMicro.tanks_being_retreated_to[nearest_unit_to_retreat_to.tag] = ally_to_enemy_distance_sq
            return True

        return False
    
    @timed
    def get_circle_around_position(self, unit: Unit, threat_position: Point2, destination: Point2) -> Point2:
        if destination == unit.position:
            return destination
        if not unit.is_flying and cy_distance_to_squared(unit.position, destination) > 225:
            path_to_destination = self.map.get_path_points(unit.position, destination)
            if len(path_to_destination) > 1:
                for path_position in path_to_destination:
                    distance_squared = cy_distance_to_squared(unit.position, path_position)
                    if distance_squared > cy_distance_to_squared(threat_position, path_position):
                        break
                    if distance_squared > 400 or path_position == path_to_destination[-1]:
                        # if no enemies along path, go to first node
                        return path_to_destination[1]
        if unit.position == threat_position:
            return destination
        threat_to_unit_vector = (unit.position - threat_position).normalized
        unit_to_destination_vector = (destination - unit.position).normalized
        if self.vectors_go_same_direction(threat_to_unit_vector, unit_to_destination_vector):
            # on same side, go directly to destination
            return destination
        tangent_vector1 = Point2((-threat_to_unit_vector.y, threat_to_unit_vector.x)) * unit.movement_speed
        tangent_vector2 = Point2((-tangent_vector1.x, -tangent_vector1.y))
        circle_around_positions = [Point2(unit.position + tangent_vector1),
                                    Point2(unit.position + tangent_vector2)]
        circle_around_positions.sort(key=lambda pos: cy_distance_to_squared(pos, destination))
        circle_around_position = Point2(cy_towards(circle_around_positions[0], threat_position, -1))
        return self.map.get_pathable_position(circle_around_position, unit)
