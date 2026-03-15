from __future__ import annotations

from loguru import logger
from typing import Dict, Tuple

from cython_extensions.geometry import (
    cy_distance_to,
    cy_distance_to_squared,
    cy_towards,
)
from cython_extensions.units_utils import cy_closer_than, cy_closest_to
from sc2.ids.ability_id import AbilityId
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.enums import CustomEffectType, TankSiegeStep, UnitMicroType
from bottato.log_helper import LogHelper
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.unit_types import UnitTypes


class SiegeTankMicro(BaseUnitMicro, GeometryMixin):
    sieged_range = 13.5
    sight_range = 11
    sieged_minimum_range = 2
    sieged_weapon_cooldown = 2.14
    unsieged_range = 7
    max_siege_time = 3.24
    sieged_count = 0
    known_tags = set()
    last_tag_refresh: float = 0
    min_seconds_between_transform = max_siege_time + 3
    last_transform_time: Dict[int, float] = {}
    last_force_move_time: Dict[int, float] = {}
    last_siege_attack_time: Dict[int, float] = {}
    previous_positions: Dict[int, Point2] = {}
    early_game_siege_positions: Dict[int, Point2] = {}
    stationary_positions: Dict[int, Tuple[Point2, float]] = {}
    early_game_siege_step: Dict[int, TankSiegeStep] = {}

    EFFECTS_TO_UNSIEGE_FOR = {
        EffectId.LIBERATORTARGETMORPHDELAYPERSISTENT,
        EffectId.LIBERATORTARGETMORPHPERSISTENT,
    }
    @timed
    def _avoid_effects(self, unit: Unit, force_move: bool) -> UnitMicroType:
        if unit.type_id != UnitTypeId.SIEGETANKSIEGED:
            return super()._avoid_effects(unit, force_move)
        for effect in self.bot.state.effects:
            # avoid liberators
            if effect.id in self.EFFECTS_TO_UNSIEGE_FOR:
                effect_radius = self.fixed_radius.get(effect.id, effect.radius)
                safe_distance = (effect_radius + unit.radius + 1.5) ** 2
                for position in effect.positions:
                    if unit.position._distance_squared(position) < safe_distance:
                        LogHelper.add_log(f"Unsieging {unit} to avoid liberator")
                        self.unsiege(unit)
                        return UnitMicroType.USE_ABILITY
        for effect in self.custom_effects_to_avoid:
            # don't block buildings
            if effect.type == CustomEffectType.BUILDING_FOOTPRINT:
                effect_radius = effect.radius
                safe_distance = (effect_radius + unit.radius + 1.5) ** 2
                if unit.distance_to_squared(effect.position) < safe_distance:
                    targets = self.enemy.get_target_closer_than(unit, max_distance=11)
                    if not targets:
                        LogHelper.add_log(f"Unsieging {unit} to avoid building footprint")
                        self.unsiege(unit)
                        return UnitMicroType.USE_ABILITY
        return UnitMicroType.NONE

    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, force_move: bool = False) -> UnitMicroType:
        # skip currently or recently transformed
        if unit.is_transforming:
            return UnitMicroType.NONE

        last_transform = self.last_transform_time.get(unit.tag, -999)
        time_since_last_transform = self.bot.time - last_transform
        is_sieged = unit.type_id == UnitTypeId.SIEGETANKSIEGED
        if self.bot.time != self.last_tag_refresh:
            self.last_tag_refresh = self.bot.time
            self.known_tags = self.bot.units.of_type({UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}).tags
            self.sieged_count = self.bot.units.of_type({UnitTypeId.SIEGETANKSIEGED}).amount
            BaseUnitMicro.depots_raised_for_tank_passage.clear()
        unsieged_count = len(self.known_tags) - self.sieged_count

        on_cooldown = time_since_last_transform < self.min_seconds_between_transform

        time_stationary_before_siege = 2.0
        if unit.tag not in self.stationary_positions:
            self.stationary_positions[unit.tag] = (unit.position, self.bot.time)
        elif unit.position.manhattan_distance(self.stationary_positions[unit.tag][0]) > 0.5:
            self.stationary_positions[unit.tag] = (unit.position, self.bot.time)
        elif self.bot.time - self.stationary_positions[unit.tag][1] > time_stationary_before_siege \
                and target.manhattan_distance(self.stationary_positions[unit.tag][0]) < 4:
            if not is_sieged:
                self.siege(unit)
                return UnitMicroType.USE_ABILITY
            return UnitMicroType.NONE
        
        enemy_distance_sq = None
        if unit.tag in BaseUnitMicro.tanks_being_retreated_to:
            enemy_distance_sq = BaseUnitMicro.tanks_being_retreated_to[unit.tag]
        elif unit.tag in BaseUnitMicro.tanks_being_retreated_to_prev_frame:
            enemy_distance_sq = BaseUnitMicro.tanks_being_retreated_to_prev_frame[unit.tag]
        if enemy_distance_sq:
            if is_sieged:
                return UnitMicroType.NONE
            if enemy_distance_sq < 400:
                self.siege(unit)
                return UnitMicroType.USE_ABILITY

        # siege tanks near main base early game
        natural_in_place = self.bot.townhalls.filter(lambda t: not t.is_flying).closer_than(5, self.map.natural_position).exists
        if not natural_in_place and 300 < self.bot.time < 420:
            for el in self.bot.expansion_locations:
                if el == self.bot.start_location:
                    continue
                for townhall in self.bot.townhalls.ready:
                    if townhall.is_flying:
                        continue
                    if townhall.distance_to_squared(el) < 16:
                        natural_in_place = True
                        break
        if (self.bot.time < 300
                or self.bot.time < 420 and not natural_in_place
                or target._distance_squared(self.bot.start_location) < 225):
            response = self._early_game_siege_tank_micro(unit, is_sieged)
            if response != UnitMicroType.NONE:
                return response
        
        if is_sieged and unit.weapon_cooldown > 0:
            self.last_siege_attack_time[unit.tag] = self.bot.time - (self.sieged_weapon_cooldown - unit.weapon_cooldown / 22.4)
        last_siege_attack = self.last_siege_attack_time.get(unit.tag, -999)
        time_since_last_siege_attack = self.bot.time - last_siege_attack

        excluded_enemy_types = {UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.ADEPTPHASESHIFT} if is_sieged else UnitTypes.NON_THREATS
        closest_enemy, closest_distance = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False,
                                                                        excluded_types=excluded_enemy_types)
        closest_distance_after_siege = closest_distance
        if not is_sieged:
            closest_distance_after_siege = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False,
                                                                        excluded_types=excluded_enemy_types, seconds_ahead=self.max_siege_time/2)[1]
        _, closest_structure_distance = self.enemy.get_target_closer_than(unit, max_distance=self.sight_range - 1, include_units=False, excluded_types={UnitTypeId.REFINERY, UnitTypeId.EXTRACTOR, UnitTypeId.ASSIMILATOR, UnitTypeId.AUTOTURRET})

        friendly_buffer_count = 0
        structures_under_threat = False
        closest_enemy_is_visible = False
        if closest_distance > 25:
            closest_enemy = None
        if closest_enemy:
            friendlies_nearer_to_enemy = self.enemy.get_units_closer_than(closest_enemy, self.bot.units, closest_distance - 0.01)
            friendly_buffer_count = len(friendlies_nearer_to_enemy)
            if closest_enemy.age == 0:
                closest_enemy_is_visible = True
                structures = self.bot.structures.filter(lambda s: s.type_id not in {UnitTypeId.AUTOTURRET, UnitTypeId.REFINERY} and not s.is_flying)
                structures_under_threat = self.enemy.in_attack_range(closest_enemy, structures, 2, first_only=True).exists

        if force_move:
            self.last_force_move_time[unit.tag] = self.bot.time
        if unit.tag in self.last_force_move_time and ((self.bot.time - self.last_force_move_time[unit.tag]) < 0.5):
            if is_sieged and (closest_distance > self.sieged_range - 2 or not closest_enemy_is_visible):
                # and friendly_buffer_count < 5:
                self.unsiege(unit)
                return UnitMicroType.USE_ABILITY
            else:
                return UnitMicroType.NONE

        tank_height = self.bot.get_terrain_height(unit.position)
        enemy_height = self.bot.get_terrain_height(closest_enemy.position) if closest_enemy else tank_height
        has_high_ground_advantage = tank_height > enemy_height
        siege_aggressively = (
            on_cooldown and not is_sieged
            or friendly_buffer_count >= 15 and unsieged_count <= self.sieged_count
        )

        closest_enemy_distance = closest_distance + 0.1 if siege_aggressively or structures_under_threat else closest_distance_after_siege
            
        # elif structures_under_threat:
        #     closest_enemy_distance = closest_distance - 0.1
        # elif has_high_ground_advantage and closest_enemy:
        #     closest_enemy_distance = closest_distance - 1

        if is_sieged:
            unsiege_range = self.sieged_range
            if time_since_last_siege_attack < 4.0:
                return UnitMicroType.NONE
                # unsiege_range += 2
            if not siege_aggressively and friendly_buffer_count >= 5:
                # keep sieged if enemy might get lured closer, decrease extra buffer over time
                unsiege_range = max(25 - min(time_since_last_transform, time_since_last_siege_attack), self.sieged_range)
            elif has_high_ground_advantage and closest_enemy:
                closer_position = Point2(cy_towards(unit.position, closest_enemy.position, 1))
                if self.bot.get_terrain_height(closer_position) < tank_height:
                    # be reluctant to leave high ground
                    unsiege_range += 5
            if closest_enemy_distance > unsiege_range and closest_structure_distance > self.sight_range - 1:
                self.unsiege(unit)
                return UnitMicroType.USE_ABILITY
        else:
        # elif closest_enemy and friendly_buffer_count >= 5 or closest_structure_distance < closest_distance:
            if has_high_ground_advantage and closest_enemy and closest_enemy_distance > self.sieged_range:
                closer_position = Point2(cy_towards(closest_enemy.position, unit.position, self.sieged_range))
                if self.bot.get_terrain_height(closer_position) == tank_height:
                    unit.move(closer_position)
                    return UnitMicroType.MOVE
            enemy_will_be_close_enough = closest_enemy_distance <= self.sieged_range or closest_structure_distance <= self.sight_range - 1
            enemy_will_be_far_enough = True if has_high_ground_advantage else closest_enemy_distance > self.sieged_minimum_range + 3
            if enemy_will_be_far_enough and enemy_will_be_close_enough:
                self.siege(unit)
                return UnitMicroType.USE_ABILITY

        return UnitMicroType.NONE

    # def attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
    #     # prefer grouped enemies

    def siege(self, unit: Unit, update_last_transform_time: bool = True):
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        self.sieged_count += 1
        if update_last_transform_time:
            self.last_transform_time[unit.tag] = self.bot.time

    def unsiege(self, unit: Unit, update_last_transform_time: bool = True):
        logger.debug(f"{unit} unsieging")
        unit(AbilityId.UNSIEGE_UNSIEGE)
        self.sieged_count -= 1
        if update_last_transform_time:
            self.last_transform_time[unit.tag] = self.bot.time

    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, move_position: Point2, force_move: bool = False) -> UnitMicroType:
        if unit.type_id == UnitTypeId.SIEGETANK:
            if force_move:
                return UnitMicroType.NONE
            return super()._attack_something(unit, health_threshold, move_position, force_move=force_move)
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if not can_attack:
            return UnitMicroType.NONE
        targets = self.enemy.in_attack_range(unit, self.bot.enemy_units)
        if not targets:
            return UnitMicroType.NONE
        sorted_targets = sorted(targets, key=lambda t: t.health + t.shield, reverse=True)
        target = sorted_targets[0]
        for target_candidate in sorted_targets:
            # find weakest target but stop if we find a target that will die from one hit
            target = target_candidate
            if target_candidate.health + target_candidate.shield < 70:
                if target_candidate.is_armored or target_candidate.health + target_candidate.shield < 40:
                    break
        # target = self.get_most_grouped_unit(targets, self.bot, range=1.25)[0]
        unit.attack(target)
        return UnitMicroType.ATTACK
    
    def _early_game_siege_tank_micro(self, unit: Unit, is_sieged: bool) -> UnitMicroType:
        closest_enemy = cy_closest_to(unit.position, self.bot.all_enemy_units) if self.bot.all_enemy_units else None
        enemy_is_in_range = False
        if closest_enemy:
            closest_enemy_distance = unit.distance_to_squared(closest_enemy)
            if closest_enemy_distance > 25:
                closest_enemy = None
            else:
                structure_in_range_distance = 10.5 if is_sieged else 10.8
                in_range_distance_sq = (structure_in_range_distance + closest_enemy.radius) ** 2 if closest_enemy.is_structure else 169
                enemy_is_in_range = closest_enemy_distance < in_range_distance_sq

        if is_sieged:
            self.early_game_siege_step[unit.tag] = TankSiegeStep.SIEGED
            if closest_enemy and not enemy_is_in_range:
                if closest_enemy.is_structure:
                    # creep out to clear structures
                    LogHelper.add_log(f"Early game siege tank micro for {unit}, closest enemy to ramp: {closest_enemy}")
                    self.unsiege(unit)
                    self.early_game_siege_step[unit.tag] = TankSiegeStep.MOVE_TO_BARRACKS
                    return UnitMicroType.USE_ABILITY
                else:
                    # fallback to normal micro to handle enemy units
                    return UnitMicroType.NONE
            # stay sieged
            return UnitMicroType.USE_ABILITY
        else:
            if closest_enemy:
                if enemy_is_in_range:
                    self.siege(unit)
                    self.early_game_siege_step[unit.tag] = TankSiegeStep.SIEGED
                    LogHelper.add_log(f"Early game siege tank sieging to cover ramp against {closest_enemy}, range {cy_distance_to(unit.position, closest_enemy.position)}")
                    return UnitMicroType.USE_ABILITY
                elif closest_enemy.is_structure:
                    unit.move(closest_enemy.position)
                    return UnitMicroType.MOVE

            ramp_top_center = self.bot.main_base_ramp.top_center
            ramp_depots = [d for d in self.bot.structures({UnitTypeId.SUPPLYDEPOTLOWERED, UnitTypeId.SUPPLYDEPOT})
                           if cy_distance_to_squared(d.position, ramp_top_center) < 25]
            
            # Calculate tank_position
            tank_position = None
            if unit.tag in self.early_game_siege_positions:
                tank_position = self.early_game_siege_positions[unit.tag]
            else:
                closest_depot_to_map_center = cy_closest_to(self.bot.game_info.map_center, ramp_depots) if ramp_depots else None
                if closest_depot_to_map_center:
                    ramp_vector = self.bot.main_base_ramp.bottom_center - ramp_top_center
                    tank_position = Point2(cy_towards(closest_depot_to_map_center.position + ramp_vector.normalized, ramp_top_center, -1))
                    self.early_game_siege_positions[unit.tag] = tank_position
            if not tank_position:
                tank_position = ramp_top_center

            step = self.early_game_siege_step.get(unit.tag, TankSiegeStep.MOVE_TO_BARRACKS)

            # Step 1: Move toward backside of ramp barracks (away from ramp)
            if step == TankSiegeStep.MOVE_TO_BARRACKS:
                ramp_barracks_list = cy_closer_than(
                    self.bot.structures({UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING}).ready,
                    5, ramp_top_center
                )
                if ramp_barracks_list:
                    ramp_barracks = ramp_barracks_list[0]
                    # backside = away from ramp
                    backside = Point2(cy_towards(ramp_top_center, ramp_barracks.position, cy_distance_to(ramp_top_center, ramp_barracks.position) + 1.5))
                    unit.move(backside)

                    near_barracks = cy_distance_to(unit.position, ramp_barracks.position) < 3.5
                    unit_ramp_distance_sq = cy_distance_to_squared(unit.position, ramp_top_center)
                    past_depots = all(
                        unit_ramp_distance_sq > cy_distance_to_squared(d.position, ramp_top_center)
                        for d in ramp_depots
                    ) if ramp_depots else True
                    if near_barracks and past_depots:
                        all_raised = True
                        for depot in ramp_depots:
                            BaseUnitMicro.depots_raised_for_tank_passage.add(depot.tag)
                            if depot.type_id == UnitTypeId.SUPPLYDEPOTLOWERED:
                                depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                                LogHelper.add_log(f"Raising depot for siege tank passage")
                                all_raised = False
                        if all_raised:
                            step = TankSiegeStep.MOVE_TO_POSITION
                            LogHelper.add_log(f"Depots raised, moving tank to position")
                else:
                    # no ramp barracks, unlikely so just use normal micro
                    return UnitMicroType.NONE

            # Step 3: Move to tank_position
            if step == TankSiegeStep.MOVE_TO_POSITION:
                # Keep depots raised while moving through
                for depot in ramp_depots:
                    BaseUnitMicro.depots_raised_for_tank_passage.add(depot.tag)

                current_distance = cy_distance_to(unit.position, tank_position)
                close_enough_to_siege = current_distance <= 0.5
                if not close_enough_to_siege and unit.tag in self.previous_positions:
                    previous_position = self.previous_positions[unit.tag]
                    previous_distance = cy_distance_to(previous_position, tank_position)
                    # siege if we're kind of close and either stop moving or start moving away
                    close_enough_to_siege = (
                        current_distance < 3 and (
                            unit.position.manhattan_distance(previous_position) < 0.1 or current_distance > previous_distance
                        )
                    )

                self.previous_positions[unit.tag] = unit.position
                if close_enough_to_siege:
                    # Step 4: Siege
                    self.siege(unit)
                    self.early_game_siege_step[unit.tag] = TankSiegeStep.SIEGED
                    self.early_game_siege_positions[unit.tag] = unit.position
                    LogHelper.add_log(f"Early game siege tank sieging at desired position")
                    return UnitMicroType.USE_ABILITY
                else:
                    unit.move(tank_position)
                    self.early_game_siege_step[unit.tag] = step
                    return UnitMicroType.MOVE

            return UnitMicroType.MOVE
