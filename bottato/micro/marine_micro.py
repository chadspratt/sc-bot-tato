from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base_unit_micro import BaseUnitMicro
from sc2.constants import UnitTypeId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class MarineMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.51
    healing_unit_tags = set()

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        return False

    async def retreat(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        if unit.health_percentage < 0.8:
            return self.retreat_to_medivac(unit)
        elif unit.tag in self.healing_unit_tags:
            if unit.health_percentage < 0.9:
                return self.retreat_to_medivac(unit)
            else:
                self.healing_unit_tags.remove(unit.tag)
        return False

    def retreat_to_medivac(self, unit: Unit) -> bool:
        medivacs = self.bot.units.filter(lambda unit: unit.type_id == UnitTypeId.MEDIVAC and unit.energy > 5)
        if not medivacs:
            return False
        nearest_medivac = medivacs.closest_to(unit)
        unit.move(nearest_medivac)
        logger.info(f"{unit} marine retreating to heal at {nearest_medivac} hp {unit.health_percentage}")
        self.healing_unit_tags.add(unit.tag)
        return True
