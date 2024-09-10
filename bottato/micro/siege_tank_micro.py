from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base_unit_micro import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from sc2.constants import UnitTypeId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class SiegeTankMicro(BaseUnitMicro, GeometryMixin):
    sieged_range = 13.5
    unsieged_range = 7
    max_siege_time = 3.24
    sieged_tags = set()
    unsieged_tags = set()
    known_tags = set()
    # siege when enemy can get within this range of siege range
    siege_buffer = -1
    # unsiege when enemy is at least this far away from being able to run back in to range before re-seiging
    unsiege_buffer = 2

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        if unit.tag not in self.known_tags:
            self.known_tags.add(unit.tag)
            self.unsieged_tags.add(unit.tag)
        if unit.is_transforming:
            return False
        is_sieged = unit.type_id == UnitTypeId.SIEGETANKSIEGED
        if is_sieged != unit.tag in self.sieged_tags:
            # fix miscategorizations
            if is_sieged:
                self.siege(unit)
            else:
                self.unsiege(unit)
        enemy_unit, unit_distance = enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=[UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE, UnitTypeId.DRONEBURROWED, UnitTypeId.MULE])
        enemy_structure, structure_distance = enemy.get_closest_target(unit, include_units=False, include_destructables=False)
        logger.info(f"{unit} seiged={is_sieged}, closest enemy {enemy_unit}({unit_distance}), structure {enemy_structure}({structure_distance})")
        enemy_range_after_sieging = 9999
        if enemy_unit:
            self.bot.client.debug_line_out(unit, enemy_unit)
            enemy_range_after_sieging = unit_distance - enemy_unit.calculate_speed() * self.max_siege_time

        if is_sieged:
            all_sieged = len(self.unsieged_tags) == 0
            enemy_distance = unit_distance if all_sieged else enemy_range_after_sieging + self.unsiege_buffer
            if enemy_distance > self.sieged_range and structure_distance > self.sieged_range:
                self.unsiege(unit)
                return True
        else:
            is_last_unseiged = len(self.unsieged_tags) == 1
            enemy_distance = unit_distance if is_last_unseiged else enemy_range_after_sieging + self.siege_buffer
            if enemy_range_after_sieging > self.unsieged_range - 2 and (enemy_distance <= self.sieged_range or structure_distance < self.sieged_range):
                self.siege(unit)
                return True
        return False

    # def attack_something(self, unit: Unit, health_threshold: float) -> bool:
    #     return super().attack_something(unit, health_threshold)

    def siege(self, unit: Unit):
        logger.info(f"{unit} sieging")
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        if unit.tag not in self.sieged_tags:
            self.sieged_tags.add(unit.tag)
        else:
            logger.info(f"{unit.tag} already in sieged_tags")
        if unit.tag in self.unsieged_tags:
            self.unsieged_tags.remove(unit.tag)
        else:
            logger.info(f"{unit.tag} not in sieged_tags")

    def unsiege(self, unit: Unit):
        logger.info(f"{unit} unsieging")
        unit(AbilityId.UNSIEGE_UNSIEGE)
        if unit.tag in self.sieged_tags:
            self.sieged_tags.remove(unit.tag)
        else:
            logger.info(f"{unit.tag} not in sieged_tags")
        if unit.tag in self.unsieged_tags:
            self.unsieged_tags.add(unit.tag)
        else:
            logger.info(f"{unit.tag} already in sieged_tags")
