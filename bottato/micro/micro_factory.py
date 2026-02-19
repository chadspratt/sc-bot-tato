from __future__ import annotations

from loguru import logger
from typing import Any, Dict

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from bottato.micro.banshee_micro import BansheeMicro
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.ghost_micro import GhostMicro
from bottato.micro.hellion_micro import HellionMicro
from bottato.micro.marauder_micro import MarauderMicro
from bottato.micro.marine_micro import MarineMicro
from bottato.micro.medivac_micro import MedivacMicro
from bottato.micro.raven_micro import RavenMicro
from bottato.micro.reaper_micro import ReaperMicro
from bottato.micro.scv_micro import SCVMicro
from bottato.micro.siege_tank_micro import SiegeTankMicro
from bottato.micro.structure_micro import StructureMicro
from bottato.micro.thor_micro import ThorMicro
from bottato.micro.viking_micro import VikingMicro
from bottato.micro.widow_mine_micro import WidowMineMicro
from bottato.tactics import Tactics

micro_instances: Dict[UnitTypeId, BaseUnitMicro] = {}
micro_lookup = {
    UnitTypeId.COMMANDCENTER: StructureMicro,
    UnitTypeId.BANSHEE: BansheeMicro,
    UnitTypeId.GHOST: GhostMicro,
    UnitTypeId.HELLION: HellionMicro,
    UnitTypeId.MARAUDER: MarauderMicro,
    UnitTypeId.MARINE: MarineMicro,
    UnitTypeId.MEDIVAC: MedivacMicro,
    UnitTypeId.RAVEN: RavenMicro,
    UnitTypeId.REAPER: ReaperMicro,
    UnitTypeId.SCV: SCVMicro,
    UnitTypeId.SIEGETANK: SiegeTankMicro,
    UnitTypeId.THOR: ThorMicro,
    UnitTypeId.VIKINGFIGHTER: VikingMicro,
    UnitTypeId.WIDOWMINE: WidowMineMicro,
}
common_objects: dict[str, Any] = {
    "bot": None,
    "enemy": None,
    "map": None,
    "my_workers": None,
    "intel": None
}


class MicroFactory:
    @staticmethod
    def set_common_objects(bot: BotAI, tactics: Tactics):
        common_objects["bot"] = bot
        common_objects["enemy"] = tactics.enemy
        common_objects["map"] = tactics.map
        common_objects["intel"] = tactics.intel

    @staticmethod
    def get_unit_micro(unit_type: Unit | UnitTypeId) -> BaseUnitMicro:
        if isinstance(unit_type, Unit):
            unit_type = unit_type.unit_alias if unit_type.unit_alias else unit_type.type_id
        if unit_type not in micro_instances:
            if unit_type in micro_lookup:
                logger.debug(f"creating {unit_type} micro for {unit_type}")
                micro_class = micro_lookup[unit_type]
                micro_instances[unit_type] = micro_class(common_objects["bot"],
                                                       common_objects["enemy"],
                                                       common_objects["map"],
                                                       common_objects["intel"])
            else:
                logger.debug(f"creating generic micro for {unit_type}")
                if UnitTypeId.NOTAUNIT not in micro_instances:
                    micro_instances[UnitTypeId.NOTAUNIT] = BaseUnitMicro(common_objects["bot"],
                                                                         common_objects["enemy"],
                                                                         common_objects["map"],
                                                                         common_objects["intel"])
                micro_instances[unit_type] = micro_instances[UnitTypeId.NOTAUNIT]

        return micro_instances[unit_type]
