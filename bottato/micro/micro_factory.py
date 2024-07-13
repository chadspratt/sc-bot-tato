from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from .base_unit_micro import BaseUnitMicro
from .reaper_micro import ReaperMicro
from .raven_micro import RavenMicro


micro_instances = {}
micro_lookup = {
    UnitTypeId.REAPER: ReaperMicro,
    UnitTypeId.RAVEN: RavenMicro
}


class MicroFactory:
    def get_unit_micro(unit: Unit, bot: BotAI) -> BaseUnitMicro:
        if unit.type_id not in micro_instances:
            if unit.type_id in micro_lookup:
                logger.info(f"creating {unit.type_id} micro for {unit}")
                micro_instances[unit.type_id] = micro_lookup[unit.type_id](bot)
            else:
                logger.info(f"creating generic micro for {unit}")
                if UnitTypeId.NOTAUNIT not in micro_instances:
                    micro_instances[UnitTypeId.NOTAUNIT] = BaseUnitMicro(bot)
                micro_instances[unit.type_id] = micro_instances[UnitTypeId.NOTAUNIT]

        return micro_instances[unit.type_id]
