from typing import Dict
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit_command import UnitCommand

from bottato.building.build_step import BuildStep
from bottato.building.special_locations import SpecialLocations
from bottato.economy.production import Production
from bottato.economy.workers import Workers
from bottato.enums import BuildResponseCode, BuildType
from bottato.map.map import Map
from bottato.mixins import timed
from bottato.upgrades import RESEARCH_ABILITIES
from bottato.unit_reference_helper import UnitReferenceHelper

class UpgradeBuildStep(BuildStep):
    upgrade_id: UpgradeId

    def __init__(self, upgrade_id: UpgradeId, bot: BotAI, workers: Workers, production: Production, map: Map):
        super().__init__(upgrade_id, bot, workers, production, map)
        self.upgrade_id = upgrade_id

    def __repr__(self) -> str:
        builder = self.unit_in_charge if self.unit_in_charge else self.builder_type
        target = self.upgrade_id.name

        return f"{target}-built by {builder}"

    def update_references(self):
        logger.debug(f"unit in charge: {self.unit_in_charge}")
        if self.unit_in_charge:
            try:
                self.unit_in_charge = UnitReferenceHelper.get_updated_unit_reference(self.unit_in_charge)
            except UnitReferenceHelper.UnitNotFound:
                self.unit_in_charge = None

    @timed
    def draw_debug_box(self):
        if self.unit_in_charge is not None:
            self.bot.client.debug_text_world(
                self.upgrade_id.name, self.unit_in_charge.position3d)

    def is_upgrade_type(self, upgrade_id: UpgradeId) -> bool:
        return self.upgrade_id == upgrade_id
    
    def tech_requirements_met(self) -> bool:
        research_structure_type: UnitTypeId = UPGRADE_RESEARCHED_FROM[self.upgrade_id]
        required_tech_building: UnitTypeId | None = RESEARCH_INFO[research_structure_type][self.upgrade_id].get(
            "required_building", None
        ) # type: ignore
        requirement_met = (
            required_tech_building is None or self.bot.structure_type_build_progress(required_tech_building) < 0.8
        )
        if not requirement_met:
            return False
        return True
    
    async def execute(self, special_locations: SpecialLocations, detected_enemy_builds: Dict[BuildType, float]) -> BuildResponseCode:
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
