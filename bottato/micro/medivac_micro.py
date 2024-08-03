from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base_unit_micro import BaseUnitMicro
from ..enemy import Enemy
from ..mixins import GeometryMixin


class MedivacMicro(BaseUnitMicro, GeometryMixin):
    heal_cost = 1
    heal_start_cost = 5
    heal_range = 4

    stopped_for_healing: set[int] = set()

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        injured_bio = self.bot.units.filter(lambda unit: unit.is_biological and unit.health_percentage < 1.0)
        if not injured_bio:
            return False
        if injured_bio.closer_than(self.heal_range, unit) and self.heal_available(unit):
            unit.stop()
            logger.info(f"{unit} stopping to heal")
            self.stopped_for_healing.add(unit.tag)
            return True
        if unit.tag in self.stopped_for_healing:
            self.stopped_for_healing.remove(unit.tag)
        return False

    def attack_something(self, unit: Unit) -> bool:
        # doesn't have an auto attack
        return False

    def heal_available(self, unit: Unit) -> bool:
        if unit.tag in self.stopped_for_healing:
            return unit.energy >= self.heal_cost
        else:
            return unit.energy >= self.heal_start_cost
