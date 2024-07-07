from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from .base_unit_micro import BaseUnitMicro
from .reaper_micro import ReaperMicro


micro_lookup = {
    UnitTypeId.REAPER: ReaperMicro
}


class MicroFactory:
    def get_unit_micro(unit: Unit, bot: BotAI) -> BaseUnitMicro:
        if unit.type_id in micro_lookup:
            logger.debug(f"creating {unit.type_id} micro for {unit}")
            return micro_lookup[unit.type_id](unit, bot)
        logger.debug(f"creating generic micro for {unit}")
        return BaseUnitMicro(unit, bot)
