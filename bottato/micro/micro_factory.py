from __future__ import annotations
from typing import Any, Dict
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

from bottato.map.map import Map
from bottato.enemy import Enemy
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.banshee_micro import BansheeMicro
from bottato.micro.hellion_micro import HellionMicro
from bottato.micro.marauder_micro import MarauderMicro
from bottato.micro.marine_micro import MarineMicro
from bottato.micro.medivac_micro import MedivacMicro
from bottato.micro.raven_micro import RavenMicro
from bottato.micro.reaper_micro import ReaperMicro
from bottato.micro.siege_tank_micro import SiegeTankMicro
from bottato.micro.viking_micro import VikingMicro


micro_instances: Dict[UnitTypeId, BaseUnitMicro] = {}
micro_lookup = {
    UnitTypeId.BANSHEE: BansheeMicro,
    UnitTypeId.HELLION: HellionMicro,
    UnitTypeId.MARAUDER: MarauderMicro,
    UnitTypeId.MARINE: MarineMicro,
    UnitTypeId.MEDIVAC: MedivacMicro,
    UnitTypeId.RAVEN: RavenMicro,
    UnitTypeId.REAPER: ReaperMicro,
    UnitTypeId.SIEGETANK: SiegeTankMicro,
    UnitTypeId.VIKINGFIGHTER: VikingMicro,
}
common_objects: dict[str, Any] = {
    "bot": None,
    "enemy": None,
    "map": None,
    "my_workers": None,
}


class MicroFactory:
    @staticmethod
    def set_common_objects(bot: BotAI, enemy: Enemy, map: Map):
        common_objects["bot"] = bot
        common_objects["enemy"] = enemy
        common_objects["map"] = map

    @staticmethod
    def get_unit_micro(unit: Unit) -> BaseUnitMicro:
        type_id = unit.unit_alias if unit.unit_alias else unit.type_id
        if type_id not in micro_instances:
            if type_id in micro_lookup:
                logger.debug(f"creating {type_id} micro for {unit}")
                micro_class = micro_lookup[type_id]
                micro_instances[type_id] = micro_class(common_objects["bot"],
                                                       common_objects["enemy"],
                                                       common_objects["map"])
            else:
                logger.debug(f"creating generic micro for {unit}")
                if UnitTypeId.NOTAUNIT not in micro_instances:
                    micro_instances[UnitTypeId.NOTAUNIT] = BaseUnitMicro(common_objects["bot"],
                                                                         common_objects["enemy"],
                                                                         common_objects["map"])
                micro_instances[type_id] = micro_instances[UnitTypeId.NOTAUNIT]

        return micro_instances[type_id]
    
    @staticmethod
    def print_timers():
        for unit_type, micro in micro_instances.items():
            micro.print_timers(unit_type.name + "-")
