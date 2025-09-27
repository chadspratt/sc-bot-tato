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

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if unit.tag not in self.known_tags:
            self.known_tags.add(unit.tag)
            self.unsieged_tags.add(unit.tag)

        # skip currently or recently transformed
        if unit.is_transforming:
            return False
        last_transform = self.last_transform_time.get(unit.tag, -999)
        time_since_last_transform = self.bot.time - last_transform
        if unit.tag in self.last_transform_time and (time_since_last_transform < self.min_seconds_between_transform):
            logger.debug(f"unit last transformed {time_since_last_transform}s ago, need to wait {self.min_seconds_between_transform}")
            return False

        # remove missing
        self.sieged_tags = self.bot.units.tags.intersection(self.sieged_tags)
        self.unsieged_tags = self.bot.units.tags.intersection(self.unsieged_tags)

        is_sieged = unit.type_id == UnitTypeId.SIEGETANKSIEGED
        if force_move:
            self.last_force_move_time[unit.tag] = self.bot.time
        if unit.tag in self.last_force_move_time and ((self.bot.time - self.last_force_move_time[unit.tag]) < 0.5):
            if is_sieged:
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

        excluded_enemy_types = [] if is_sieged else [UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.DRONEBURROWED, UnitTypeId.MULE]
        closest_enemy, closest_distance = enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=excluded_enemy_types)
        closest_enemy_after_siege, closest_distance_after_siege = enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=excluded_enemy_types, seconds_ahead=self.max_siege_time)
        closest_structure, closest_structure_distance = enemy.get_closest_target(unit, include_units=False, include_destructables=False)

        # logger.debug(f"{unit} seiged={is_sieged}, closest enemy {closest_enemy}({closest_distance}), structure {closest_structure}({closest_structure_distance})")

        reached_destination = unit.position.distance_to(target) < 0.5

        has_friendly_buffer = True
        if closest_enemy:
            friendlies_nearest_to_enemy = self.bot.units.closest_n_units(closest_enemy.position, 5)
            has_friendly_buffer = unit not in friendlies_nearest_to_enemy
        # enemy_range_after_sieging = 9999
        # if closest_enemy:
        #     self.bot.client.debug_line_out(unit, closest_enemy)
        #     enemy_range_after_sieging = enemy_unit_distance
        #     if closest_enemy.is_facing(unit, 0.2):
        #         enemy_range_after_sieging -= closest_enemy.calculate_speed() * self.max_siege_time * 0.8

        most_are_seiged = len(self.unsieged_tags) < len(self.sieged_tags)
        enemy_distance = closest_distance if most_are_seiged or has_friendly_buffer else closest_distance_after_siege
        if is_sieged:
            # all_sieged = len(self.unsieged_tags) == 0
            # keep sieged if enemy might get lured closer, decrease extra buffer over time
            extra_range = max(15 - time_since_last_transform, 0)
            if enemy_distance > self.sieged_range + extra_range and closest_structure_distance > self.sight_range - 1 and not reached_destination:
                self.unsiege(unit)
                return True
        else:
            enemy_will_be_far_enough = enemy_will_be_close_enough = False
            if has_friendly_buffer:
                enemy_will_be_far_enough = closest_distance > self.sieged_minimum_range + 2
                enemy_will_be_close_enough = closest_distance <= self.sieged_range or closest_structure_distance <= self.sight_range - 1
            else:
                enemy_will_be_far_enough = closest_distance_after_siege > self.sieged_minimum_range + 0.5
                enemy_will_be_close_enough = enemy_distance <= self.sieged_range or closest_structure_distance <= self.sight_range - 1
            if enemy_will_be_far_enough and enemy_will_be_close_enough:
                self.siege(unit)
                return True

        return False

    # def attack_something(self, unit: Unit, enemy: Enemy, health_threshold: float, force_move: bool = False) -> bool:
    #     return super().attack_something(unit, enemy, health_threshold)

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
        new_list = self.bot.units.tags.intersection(new_list)
        if unit.tag not in new_list:
            new_list.add(unit.tag)
        else:
            logger.debug(f"{unit.tag} already in unsieged_tags")
        if unit.tag in old_list:
            old_list.remove(unit.tag)
        else:
            logger.debug(f"{unit.tag} not in sieged_tags")
