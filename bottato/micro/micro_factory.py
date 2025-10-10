from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

from bottato.enemy import Enemy
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.reaper_micro import ReaperMicro
from bottato.micro.raven_micro import RavenMicro
from bottato.micro.siege_tank_micro import SiegeTankMicro
from bottato.micro.medivac_micro import MedivacMicro
from bottato.micro.marine_micro import MarineMicro
from bottato.micro.banshee_micro import BansheeMicro


micro_instances = {}
micro_lookup = {
    UnitTypeId.REAPER: ReaperMicro,
    UnitTypeId.MARINE: MarineMicro,
    UnitTypeId.RAVEN: RavenMicro,
    UnitTypeId.SIEGETANK: SiegeTankMicro,
    # UnitTypeId.SIEGETANKSIEGED: SiegeTankMicro,
    UnitTypeId.MEDIVAC: MedivacMicro,
    UnitTypeId.BANSHEE: BansheeMicro,
}


class MicroFactory:
    def get_unit_micro(unit: Unit, bot: BotAI, enemy: Enemy) -> BaseUnitMicro:
        type_id = unit.unit_alias if unit.unit_alias else unit.type_id
        if type_id not in micro_instances:
            if type_id in micro_lookup:
                logger.debug(f"creating {type_id} micro for {unit}")
                micro_instances[type_id] = micro_lookup[type_id](bot, enemy)
            else:
                logger.debug(f"creating generic micro for {unit}")
                if UnitTypeId.NOTAUNIT not in micro_instances:
                    micro_instances[UnitTypeId.NOTAUNIT] = BaseUnitMicro(bot, enemy)
                micro_instances[type_id] = micro_instances[UnitTypeId.NOTAUNIT]

        return micro_instances[type_id]
