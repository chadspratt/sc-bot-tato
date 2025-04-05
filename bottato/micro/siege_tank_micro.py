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
    unsieged_range = 7
    max_siege_time = 3.24
    sieged_tags = set()
    unsieged_tags = set()
    known_tags = set()
    min_seconds_between_transform = max_siege_time + 1
    last_transform_time: dict[int, float] = {}

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float) -> bool:
        if unit.tag not in self.known_tags:
            self.known_tags.add(unit.tag)
            self.unsieged_tags.add(unit.tag)

        # skip currently or recently transformed
        if unit.is_transforming:
            return False
        if unit.tag in self.last_transform_time and ((self.bot.time - self.last_transform_time[unit.tag]) < self.min_seconds_between_transform):
            logger.info(f"unit last transformed {self.bot.time - self.last_transform_time[unit.tag]}s ago, need to wait {self.min_seconds_between_transform}")
            return False

        # remove missing
        self.sieged_tags = self.bot.units.tags.intersection(self.sieged_tags)
        self.unsieged_tags = self.bot.units.tags.intersection(self.unsieged_tags)

        is_sieged = unit.type_id == UnitTypeId.SIEGETANKSIEGED
        # fix miscategorizations
        if is_sieged != (unit.tag in self.sieged_tags):
            if is_sieged:
                self.siege(unit)
            else:
                self.unsiege(unit)

        excluded_enemy_types = [] if is_sieged else [UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.DRONEBURROWED, UnitTypeId.MULE]
        enemy_unit, enemy_unit_distance = enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=excluded_enemy_types)
        enemy_structure, structure_distance = enemy.get_closest_target(unit, include_units=False, include_destructables=False)

        logger.info(f"{unit} seiged={is_sieged}, closest enemy {enemy_unit}({enemy_unit_distance}), structure {enemy_structure}({structure_distance})")

        reached_destination = unit.position.distance_to(target) < 0.5

        enemy_range_after_sieging = 9999
        if enemy_unit:
            self.bot.client.debug_line_out(unit, enemy_unit)
            enemy_range_after_sieging = enemy_unit_distance
            if enemy_unit.is_facing(unit, 0.2):
                enemy_range_after_sieging -= enemy_unit.calculate_speed() * self.max_siege_time * 0.8

        most_are_seiged = len(self.unsieged_tags) < len(self.sieged_tags)
        enemy_distance = enemy_unit_distance if most_are_seiged else enemy_range_after_sieging
        if is_sieged:
            # all_sieged = len(self.unsieged_tags) == 0
            if enemy_distance > self.sieged_range and structure_distance > self.sight_range - 1 and not reached_destination:
                self.unsiege(unit)
                return True
        else:
            enemy_will_be_far_enough = enemy_range_after_sieging > self.sieged_minimum_range + 0.5
            enemy_will_be_close_enough = enemy_distance <= self.sieged_range or structure_distance <= self.sight_range - 1
            if enemy_will_be_far_enough and enemy_will_be_close_enough:
                self.siege(unit)
                return True

        return False

    # def attack_something(self, unit: Unit, health_threshold: float) -> bool:
    #     return super().attack_something(unit, health_threshold)

    def siege(self, unit: Unit):
        logger.info(f"{unit} sieging")
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        self.update_siege_state(unit, self.unsieged_tags, self.sieged_tags)

    def unsiege(self, unit: Unit):
        logger.info(f"{unit} unsieging")
        unit(AbilityId.UNSIEGE_UNSIEGE)
        self.update_siege_state(unit, self.sieged_tags, self.unsieged_tags)

    def update_siege_state(self, unit: Unit, old_list: set, new_list: set):
        self.last_transform_time[unit.tag] = self.bot.time
        new_list = self.bot.units.tags.intersection(new_list)
        if unit.tag not in new_list:
            new_list.add(unit.tag)
        else:
            logger.info(f"{unit.tag} already in unsieged_tags")
        if unit.tag in old_list:
            old_list.remove(unit.tag)
        else:
            logger.info(f"{unit.tag} not in sieged_tags")
