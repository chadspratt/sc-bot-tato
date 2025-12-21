from loguru import logger

from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit_command import UnitCommand
from sc2.unit import Unit

from bottato.mixins import timed, timed_async
from bottato.map.map import Map
from bottato.economy.workers import Workers
from bottato.economy.production import Production
from bottato.building.build_step import BuildStep
from bottato.building.special_locations import SpecialLocations
from bottato.upgrades import RESEARCH_ABILITIES
from bottato.enums import BuildResponseCode, RushType

class UpgradeBuildStep(BuildStep):
    upgrade_id: UpgradeId

    def __init__(self, upgrade_id: UpgradeId, bot: BotAI, workers: Workers, production: Production, map: Map):
        super().__init__(upgrade_id, bot, workers, production, map)
        self.upgrade_id = upgrade_id

    def __repr__(self) -> str:
        builder = self.unit_in_charge if self.unit_in_charge else self.builder_type
        target = self.upgrade_id.name

        return f"{target}-built by {builder}"

    def update_references(self, units_by_tag: dict[int, Unit]):
        logger.debug(f"unit in charge: {self.unit_in_charge}")
        if self.unit_in_charge:
            try:
                self.unit_in_charge = self.get_updated_unit_reference(self.unit_in_charge, self.bot, units_by_tag)
            except self.UnitNotFound:
                self.unit_in_charge = None

    @timed
    def draw_debug_box(self):
        if self.unit_in_charge is not None:
            self.bot.client.debug_text_world(
                self.upgrade_id.name, self.unit_in_charge.position3d)

    def is_upgrade_type(self, upgrade_id: UpgradeId) -> bool:
        return self.upgrade_id == upgrade_id
    
    @timed_async
    async def execute(self, special_locations: SpecialLocations, rush_detected_types: set[RushType]) -> BuildResponseCode:
        response = None

        logger.debug(f"researching upgrade {self.upgrade_id}")
        if self.unit_in_charge is None:
            self.unit_in_charge = self.production.get_research_facility(self.upgrade_id)
            logger.debug(f"research facility: {self.unit_in_charge}")
        if self.unit_in_charge is None or self.unit_in_charge.type_id == UnitTypeId.TECHLAB:
            response = BuildResponseCode.NO_FACILITY
        else:
            # successful_action: bool = self.unit_in_charge.research(self.upgrade_id)
            ability = RESEARCH_ABILITIES[self.upgrade_id]

            required_tech_building: UnitTypeId | None = RESEARCH_INFO[self.unit_in_charge.type_id][self.upgrade_id].get(
                "required_building", None
            ) # type: ignore
            requirement_met = (
                required_tech_building is None or self.bot.structure_type_build_progress(required_tech_building) == 1
            )
            if not requirement_met:
                return BuildResponseCode.NO_TECH
            logger.debug(f"{self.unit_in_charge} researching upgrade with ability {ability}")
            successful_action: UnitCommand | bool = self.unit_in_charge(ability)
            if successful_action:
                response = BuildResponseCode.SUCCESS
                self.is_in_progress = True

        if response is None:
            logger.debug("upgrade failed to start")
            response = BuildResponseCode.FAILED

        return response

    async def is_interrupted(self) -> bool:
        if self.unit_in_charge is None or self.unit_in_charge.is_idle:
            self.is_in_progress = False
            return True        
        return False
