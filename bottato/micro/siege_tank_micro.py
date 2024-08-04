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
    sieged_range = 13
    max_siege_time = 3.24
    # sieged_tank_tags = set()

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        is_sieged = unit.type_id == UnitTypeId.SIEGETANKSIEGED
        enemy_unit, unit_distance = enemy.get_closest_target(unit, include_structures=False)
        enemy_structure, structure_distance = enemy.get_closest_target(unit, include_units=False)
        logger.info(f"{unit} seiged={is_sieged}, closest enemy {enemy_unit}({unit_distance}), structure {enemy_structure}({structure_distance})")
        if is_sieged:
            if unit_distance > 25 and structure_distance > self.sieged_range:
                self.unsiege(unit)
                return True
        if enemy_unit:
            enemy_range_after_sieging = unit_distance - enemy_unit.calculate_speed() * self.max_siege_time
            if enemy_range_after_sieging <= self.sieged_range - 1:
                self.siege(unit)
                return True
        if enemy_structure:
            if structure_distance < self.sieged_range:
                self.siege(unit)
                return True
        return False

    def siege(self, unit: Unit):
        logger.info(f"{unit} sieging")
        unit(AbilityId.SIEGEMODE_SIEGEMODE)
        # self.sieged_tank_tags.add(unit.tag)

    def unsiege(self, unit: Unit):
        logger.info(f"{unit} unsieging")
        unit(AbilityId.UNSIEGE_UNSIEGE)
        # self.sieged_tank_tags.remove(unit.tag)
