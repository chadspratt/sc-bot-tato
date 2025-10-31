from __future__ import annotations
from loguru import logger

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base_unit_micro import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from sc2.constants import UnitTypeId
from ..enemy import Enemy
from ..mixins import GeometryMixin


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
    min_seconds_between_transform = max_siege_time + 1
    last_transform_time: dict[int, float] = {}
    last_force_move_time: dict[int, float] = {}
    last_siege_attack_time: dict[int, float] = {}
    previous_positions: dict[int, Point2] = {}
    early_game_siege_positions: dict[int, Point2] = {}

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if unit.tag not in self.known_tags:
            self.known_tags.add(unit.tag)
            self.unsieged_tags.add(unit.tag)

        # skip currently or recently transformed
        if unit.is_transforming:
            return False
        last_transform = self.last_transform_time.get(unit.tag, -999)
        time_since_last_transform = self.bot.time - last_transform

        is_sieged = unit.type_id == UnitTypeId.SIEGETANKSIEGED

        # siege tanks near main base early game
        if self.bot.time < 300 or self.bot.time < 420 and len(self.bot.townhalls) < 3:
            if unit.tag not in self.previous_positions:
                self.previous_positions[unit.tag] = unit.position
            if not is_sieged:
                if unit.tag in self.early_game_siege_positions:
                    tank_position = self.early_game_siege_positions[unit.tag]
                else:
                    tank_position = None
                    bunkers = self.bot.structures(UnitTypeId.BUNKER)
                    bunker: Unit = bunkers[0] if bunkers else None
                    if bunker and bunker.distance_to(self.bot.main_base_ramp.top_center) > 5:
                        # bunker on low ground, position tank to cover it, a bit away from top of ramp
                        tank_positions = self.get_triangle_point_c(bunker.position, self.bot.main_base_ramp.top_center, 10.5, 5)
                        if tank_positions:
                            high_ground_height = self.bot.get_terrain_height(self.bot.main_base_ramp.top_center)
                            for position in tank_positions:
                                if abs(self.bot.get_terrain_height(position) - high_ground_height) < 5:
                                    if tank_position is None or tank_position.distance_to(self.bot.game_info.map_center) > position.distance_to(self.bot.game_info.map_center):
                                        tank_position = position
                        if not tank_position:
                            tank_position = bunker.position.towards(unit, 10.5)

                if tank_position:
                    current_distance = unit.distance_to(tank_position)
                    previous_distance = self.previous_positions[unit.tag].distance_to(tank_position)
                    if current_distance <= 0.5:
                        self.siege(unit)
                    elif current_distance < 3 and (unit.position.manhattan_distance(self.previous_positions[unit.tag]) < 0.1 or current_distance > previous_distance):
                        closest_depot = self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).closest_to(unit)
                        depot_distance = closest_depot.distance_to(unit)
                        if depot_distance < 2.2:
                            tank_position = closest_depot.position.towards(unit.position, 4)
                            unit.move(tank_position)
                        else:
                            self.siege(unit)
                    else:
                        unit.move(tank_position)
                    self.early_game_siege_positions[unit.tag] = tank_position
                elif unit.distance_to(self.bot.main_base_ramp.bottom_center) > 11:
                    unit.move(self.bot.main_base_ramp.bottom_center.towards(unit.position, 10.5))
                else:
                    self.siege(unit)
            self.previous_positions[unit.tag] = unit.position
            return True
        
        transform_cooldown = 0
        if unit.tag in self.last_transform_time and time_since_last_transform < self.min_seconds_between_transform:
            logger.debug(f"unit last transformed {time_since_last_transform}s ago, need to wait {self.min_seconds_between_transform}")
            transform_cooldown = self.min_seconds_between_transform - time_since_last_transform
            # return False

        # remove missing
        self.sieged_tags = self.bot.units.tags.intersection(self.sieged_tags)
        self.unsieged_tags = self.bot.units.tags.intersection(self.unsieged_tags)
        if force_move:
            self.last_force_move_time[unit.tag] = self.bot.time
        
        if is_sieged and unit.weapon_cooldown > 0:
            self.last_siege_attack_time[unit.tag] = self.bot.time - (self.sieged_weapon_cooldown - unit.weapon_cooldown / 22.4)
        last_siege_attack = self.last_siege_attack_time.get(unit.tag, -999)
        time_since_last_siege_attack = self.bot.time - last_siege_attack

        excluded_enemy_types = [] if is_sieged else [UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.DRONEBURROWED, UnitTypeId.MULE]
        closest_enemy, closest_distance = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=excluded_enemy_types)
        closest_enemy_after_siege, closest_distance_after_siege = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=excluded_enemy_types, seconds_ahead=self.max_siege_time/2)
        closest_structure, closest_structure_distance = self.enemy.get_target_closer_than(unit, max_distance=self.sight_range - 1,include_units=False)

        if transform_cooldown > 0 and not is_sieged:
            # try to actually get in range during cooldown
            closest_distance_after_siege = closest_distance

        # reached_destination = unit.position.distance_to(target) < 2
        # if reached_destination:
        #     if not is_sieged:
        #         self.siege(unit)
        #         return True
        #     return False

        if unit.tag in self.last_force_move_time and ((self.bot.time - self.last_force_move_time[unit.tag]) < 0.5):
            if is_sieged and (closest_distance > self.sieged_range - 2 or closest_enemy.age != 0):
                self.unsiege(unit)
                return True
            else:
                return False
        # fix miscategorizations
        if is_sieged != (unit.tag in self.sieged_tags):
            if is_sieged:
                self.siege(unit, update_last_transform_time=False)
            else:
                self.unsiege(unit, update_last_transform_time=False)

        has_friendly_buffer = True
        if closest_enemy:
            friendlies_nearest_to_enemy = self.bot.units.closest_n_units(closest_enemy.position, 5)
            has_friendly_buffer = unit not in friendlies_nearest_to_enemy

        # most_are_seiged = len(self.unsieged_tags) < len(self.sieged_tags)
        # enemy_distance = closest_distance if most_are_seiged or has_friendly_buffer else closest_distance_after_siege
        if is_sieged:
            # all_sieged = len(self.unsieged_tags) == 0
            # keep sieged if enemy might get lured closer, decrease extra buffer over time
            # if reached_destination:
            #     return False
            tank_height = self.bot.get_terrain_height(unit.position)
            enemy_height = self.bot.get_terrain_height(closest_enemy.position) if closest_enemy else tank_height
            unsiege_range = self.sieged_range
            if has_friendly_buffer:
                unsiege_range = max(25 - min(time_since_last_transform, time_since_last_siege_attack), self.sieged_range)
            if tank_height > enemy_height:
                # be reluctant to leave high ground
                unsiege_range += 5
            if closest_distance > unsiege_range and closest_structure_distance > self.sight_range - 1:
                self.unsiege(unit)
                return True
        else:
            enemy_will_be_far_enough = enemy_will_be_close_enough = False
            if has_friendly_buffer:
                enemy_will_be_far_enough = closest_distance > self.sieged_minimum_range + 2
                enemy_will_be_close_enough = closest_distance_after_siege <= self.sieged_range or closest_structure_distance <= self.sight_range - 1
            else:
                enemy_will_be_far_enough = closest_distance_after_siege > self.sieged_minimum_range + 0.5
                enemy_will_be_close_enough = closest_distance_after_siege <= self.sieged_range or closest_structure_distance <= self.sight_range - 1
            if enemy_will_be_far_enough and enemy_will_be_close_enough:
                self.siege(unit)
                return True

        return False

    # def attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
    #     return super().attack_something(unit, health_threshold)

    def siege(self, unit: Unit, update_last_transform_time: bool = True):
        logger.debug(f"{unit} sieging")
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
