from __future__ import annotations
from typing import Dict, Tuple
from loguru import logger

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bottato.enums import UnitMicroType
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
    sieged_tags = set()
    unsieged_tags = set()
    known_tags = set()
    min_seconds_between_transform = max_siege_time + 3
    last_transform_time: Dict[int, float] = {}
    last_force_move_time: Dict[int, float] = {}
    last_siege_attack_time: Dict[int, float] = {}
    previous_positions: Dict[int, Point2] = {}
    early_game_siege_positions: Dict[int, Point2] = {}
    bunker_count: int = 0
    stationary_positions: Dict[int, Tuple[Point2, float]] = {}

    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> UnitMicroType:
        if unit.tag not in self.known_tags:
            self.known_tags.add(unit.tag)
            self.unsieged_tags.add(unit.tag)

        # skip currently or recently transformed
        if unit.is_transforming:
            return UnitMicroType.NONE

        last_transform = self.last_transform_time.get(unit.tag, -999)
        time_since_last_transform = self.bot.time - last_transform
        is_sieged = unit.type_id == UnitTypeId.SIEGETANKSIEGED
        if is_sieged != (unit.tag in self.sieged_tags):
            # fix miscategorizations, though it's probably just transforming
            if time_since_last_transform > 1.5:
                if is_sieged:
                    self.siege(unit, update_last_transform_time=False)
                else:
                    self.unsiege(unit, update_last_transform_time=False)
            return UnitMicroType.USE_ABILITY

        on_cooldown = time_since_last_transform < self.min_seconds_between_transform

        # siege if stationary for 4s
        if unit.tag not in self.stationary_positions:
            self.stationary_positions[unit.tag] = (unit.position, self.bot.time)
        elif unit.position.manhattan_distance(self.stationary_positions[unit.tag][0]) > 0.5:
            self.stationary_positions[unit.tag] = (unit.position, self.bot.time)
        elif self.bot.time - self.stationary_positions[unit.tag][1] > 2 \
                and target.manhattan_distance(self.stationary_positions[unit.tag][0]) < 4:
            if not is_sieged:
                self.siege(unit)
            return UnitMicroType.NONE
        
        enemy_distance = None
        if unit.tag in BaseUnitMicro.tanks_being_retreated_to:
            enemy_distance = BaseUnitMicro.tanks_being_retreated_to[unit.tag]
        elif unit.tag in BaseUnitMicro.tanks_being_retreated_to_prev_frame:
            enemy_distance = BaseUnitMicro.tanks_being_retreated_to_prev_frame[unit.tag]
        if enemy_distance:
            if is_sieged:
                return UnitMicroType.NONE
            if enemy_distance < 18:
                self.siege(unit)
                return UnitMicroType.USE_ABILITY

        # siege tanks near main base early game
        natural_in_place = len(self.bot.townhalls) > 2
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
        if self.bot.time < 300 or self.bot.time < 420 and not natural_in_place or target._distance_squared(self.bot.start_location) < 225:
            return self._early_game_siege_tank_micro(unit, is_sieged)

        # remove missing
        self.sieged_tags = self.bot.units.tags.intersection(self.sieged_tags)
        self.unsieged_tags = self.bot.units.tags.intersection(self.unsieged_tags)
        
        if is_sieged and unit.weapon_cooldown > 0:
            self.last_siege_attack_time[unit.tag] = self.bot.time - (self.sieged_weapon_cooldown - unit.weapon_cooldown / 22.4)
        last_siege_attack = self.last_siege_attack_time.get(unit.tag, -999)
        time_since_last_siege_attack = self.bot.time - last_siege_attack

        excluded_enemy_types = [UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.ADEPTPHASESHIFT] if is_sieged else UnitTypes.NON_THREATS
        closest_enemy, closest_distance = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False,
                                                                        excluded_types=excluded_enemy_types)
        closest_distance_after_siege = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False,
                                                                     excluded_types=excluded_enemy_types, seconds_ahead=self.max_siege_time/2)[1]
        _, closest_structure_distance = self.enemy.get_target_closer_than(unit, max_distance=self.sight_range - 1, include_units=False)

        friendly_buffer_count = 0
        structures_under_threat = False
        closest_enemy_is_visible = False
        if closest_distance > 25:
            closest_enemy = None
        if closest_enemy:
            friendlies_nearer_to_enemy = self.units_closer_than(closest_enemy, self.bot.units, closest_distance - 0.01, self.bot)
            friendly_buffer_count = len(friendlies_nearer_to_enemy)
            if closest_enemy.age == 0:
                closest_enemy_is_visible = True
                structures = self.bot.structures.filter(lambda s: s.type_id != UnitTypeId.AUTOTURRET)
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
        siege_aggressively = on_cooldown and not is_sieged or friendly_buffer_count >= 15 and len(self.unsieged_tags) <= len(self.sieged_tags)

        closest_enemy_distance = closest_distance_after_siege
        if structures_under_threat or siege_aggressively or has_high_ground_advantage and closest_enemy:
            # enemy might be immobile while attacking structures, so only siege if in range now
            closest_enemy_distance = closest_distance + 0.5

        if is_sieged:
            unsiege_range = self.sieged_range
            if time_since_last_siege_attack < 2.0:
                unsiege_range += 2
            if not siege_aggressively and friendly_buffer_count >= 5:
                # keep sieged if enemy might get lured closer, decrease extra buffer over time
                unsiege_range = max(25 - min(time_since_last_transform, time_since_last_siege_attack), self.sieged_range)
            elif has_high_ground_advantage and closest_enemy:
                closer_position = unit.position.towards(closest_enemy.position, 1)
                if self.bot.get_terrain_height(closer_position) < tank_height:
                    # be reluctant to leave high ground
                    unsiege_range += 5
            if closest_enemy_distance > unsiege_range and closest_structure_distance > self.sight_range - 1:
                self.unsiege(unit)
                return UnitMicroType.USE_ABILITY
        else:
        # elif closest_enemy and friendly_buffer_count >= 5 or closest_structure_distance < closest_distance:
            if has_high_ground_advantage and closest_enemy and closest_enemy_distance > self.sieged_range:
                closer_position = closest_enemy.position.towards(unit, self.sieged_range)
                if self.bot.get_terrain_height(closer_position) == tank_height:
                    unit.move(closer_position)
                    return UnitMicroType.MOVE
            enemy_will_be_close_enough = closest_enemy_distance <= self.sieged_range or closest_structure_distance <= self.sight_range - 1
            enemy_will_be_far_enough = True if has_high_ground_advantage else closest_distance > self.sieged_minimum_range + 3
            if enemy_will_be_far_enough and enemy_will_be_close_enough:
                self.siege(unit)
                return UnitMicroType.USE_ABILITY

        return UnitMicroType.NONE

    # def attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
    #     # prefer grouped enemies

    def siege(self, unit: Unit, update_last_transform_time: bool = True):
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        self.update_siege_state(unit, self.unsieged_tags, self.sieged_tags, update_last_transform_time)

    def unsiege(self, unit: Unit, update_last_transform_time: bool = True):
        logger.debug(f"{unit} unsieging")
        unit(AbilityId.UNSIEGE_UNSIEGE)
        self.update_siege_state(unit, self.sieged_tags, self.unsieged_tags, update_last_transform_time)

    def update_siege_state(self, unit: Unit, old_list: set, new_list: set, update_last_transform_time: bool = True):
        if update_last_transform_time:
            self.last_transform_time[unit.tag] = self.bot.time
        # new_list = self.bot.units.tags.intersection(new_list)
        if unit.tag not in new_list:
            new_list.add(unit.tag)
        else:
            logger.debug(f"{unit.tag} already in unsieged_tags")
        if unit.tag in old_list:
            old_list.remove(unit.tag)
        else:
            logger.debug(f"{unit.tag} not in sieged_tags")

    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> UnitMicroType:
        if unit.type_id == UnitTypeId.SIEGETANK:
            if force_move:
                return UnitMicroType.NONE
            return super()._attack_something(unit, health_threshold, force_move)
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if not can_attack:
            return UnitMicroType.NONE
        targets = self.enemy.in_attack_range(unit, self.bot.enemy_units)
        if not targets:
            return UnitMicroType.NONE
        target = self.get_most_grouped_unit(targets, self.bot, range=1.25)[0]
        unit.attack(target)
        return UnitMicroType.ATTACK
    
    def _early_game_siege_tank_micro(self, unit: Unit, is_sieged: bool) -> UnitMicroType:
        enemies_near_ramp = self.bot.all_enemy_units.closer_than(20, self.bot.main_base_ramp.bottom_center)
        closest_enemy_to_ramp = enemies_near_ramp.closest_to(unit) if enemies_near_ramp else None
        enemy_out_of_range = False
        if closest_enemy_to_ramp:
            structure_in_range_distance = 10.5 if is_sieged else 10.8
            in_range_distance_sq = (structure_in_range_distance + closest_enemy_to_ramp.radius) ** 2 if closest_enemy_to_ramp.is_structure else 169
            enemy_out_of_range = unit.distance_to_squared(closest_enemy_to_ramp) >= in_range_distance_sq
        if unit.tag not in self.previous_positions:
            self.previous_positions[unit.tag] = unit.position
        if is_sieged:
            if self.bunker_count != len(self.bot.structures(UnitTypeId.BUNKER)):
                # reposition to cover new bunker
                self.bunker_count = len(self.bot.structures(UnitTypeId.BUNKER))
                self.unsiege(unit)
                if unit.tag in self.early_game_siege_positions:
                    del self.early_game_siege_positions[unit.tag]
                return UnitMicroType.USE_ABILITY
            if closest_enemy_to_ramp and closest_enemy_to_ramp.is_structure and enemy_out_of_range:
                # creep out to clear structures
                LogHelper.add_log(f"Early game siege tank micro for {unit}, closest enemy to ramp: {closest_enemy_to_ramp}")
                self.unsiege(unit)
                return UnitMicroType.USE_ABILITY
        else:
            if closest_enemy_to_ramp:
                if enemy_out_of_range:
                    if closest_enemy_to_ramp.is_structure:
                        unit.move(closest_enemy_to_ramp.position)
                        return UnitMicroType.MOVE
                else:
                    self.siege(unit)
                    LogHelper.add_log(f"Early game siege tank sieging to cover ramp against {closest_enemy_to_ramp}, range {unit.distance_to(closest_enemy_to_ramp)}")
                    return UnitMicroType.USE_ABILITY
            if unit.tag in self.early_game_siege_positions:
                tank_position = self.early_game_siege_positions[unit.tag]
            else:
                tank_position = None
                bunkers = self.bot.structures(UnitTypeId.BUNKER)
                bunker: Unit | None = bunkers.furthest_to(self.bot.main_base_ramp.top_center) if bunkers else None
                if bunker and bunker.distance_to_squared(self.bot.main_base_ramp.top_center) > 36:
                    # bunker on low ground, position tank to cover it, a bit away from top of ramp
                    tank_positions = self.get_triangle_point_c(bunker.position, self.bot.main_base_ramp.top_center, 10.5, 5)
                    if tank_positions:
                        high_ground_height = self.bot.get_terrain_height(self.bot.main_base_ramp.top_center)
                        for position in tank_positions:
                            if abs(self.bot.get_terrain_height(position) - high_ground_height) < 5:
                                if tank_position is None or tank_position._distance_squared(self.bot.game_info.map_center) > position._distance_squared(self.bot.game_info.map_center):
                                    tank_position = position
                    if not tank_position:
                        tank_position = bunker.position.towards(unit, 10.5)

            if tank_position:
                current_distance = unit.distance_to(tank_position)
                previous_distance = self.previous_positions[unit.tag].distance_to(tank_position)
                if current_distance <= 0.5:
                    # don't block barracks addon from building
                    barracks = self.bot.structures(UnitTypeId.BARRACKS).ready
                    if barracks:
                        barracks_addon_position = barracks.closest_to(unit).add_on_position
                        addon_distance = barracks_addon_position.distance_to(unit)
                        if addon_distance < 2:
                            tank_position = barracks_addon_position.towards(unit.position, 1)
                            unit.move(tank_position)
                            return UnitMicroType.MOVE
                    self.siege(unit)
                    LogHelper.add_log(f"Early game siege tank sieging to cover ramp at desired position")
                elif current_distance < 3 and (unit.position.manhattan_distance(self.previous_positions[unit.tag]) < 0.1 or current_distance > previous_distance):
                    # don't block depots from raising
                    closest_depot = self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).closest_to(unit)
                    depot_distance = min(abs(closest_depot.position.x - unit.position.x), abs(closest_depot.position.y - unit.position.y))
                    if depot_distance < 2.3:
                        tank_position = closest_depot.position.towards(unit.position, 4)
                        unit.move(tank_position)
                    else:
                        self.siege(unit)
                        LogHelper.add_log(f"Early game siege tank sieging to cover ramp at closest possible position")
                else:
                    unit.move(tank_position)
                self.early_game_siege_positions[unit.tag] = tank_position
            elif unit.distance_to(self.bot.main_base_ramp.bottom_center) > 9:
                unit.move(self.bot.main_base_ramp.bottom_center)
            else:
                self.siege(unit)
                LogHelper.add_log(f"Early game siege tank sieging to cover ramp at default position")
        self.previous_positions[unit.tag] = unit.position
        return UnitMicroType.USE_ABILITY
