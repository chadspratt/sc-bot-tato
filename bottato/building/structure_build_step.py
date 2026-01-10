from typing import Dict
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from bottato.mixins import timed, timed_async
from bottato.log_helper import LogHelper
from bottato.enums import BuildResponseCode, BuildType
from bottato.unit_types import UnitTypes
from bottato.map.map import Map
from bottato.economy.workers import Workers
from bottato.economy.production import Production
from bottato.building.build_step import BuildStep
from bottato.building.special_locations import SpecialLocations
from bottato.tech_tree import TECH_TREE
from bottato.unit_reference_helper import UnitReferenceHelper

class StructureBuildStep(BuildStep):
    unit_type_id: UnitTypeId
    unit_being_built: Unit | None = None
    position: Point2 | None = None

    def __init__(self, unit_type_id: UnitTypeId, bot: BotAI, workers: Workers, production: Production, map: Map):
        super().__init__(unit_type_id, bot, workers, production, map)
        self.unit_type_id = unit_type_id

    def __repr__(self) -> str:
        builder = self.unit_in_charge if self.unit_in_charge else self.builder_type
        target = self.unit_type_id.name

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
                self.unit_type_id.name, self.unit_in_charge.position3d)
    
    def is_unit_type(self, unit_type_id: UnitTypeId | UpgradeId) -> bool:
        if isinstance(unit_type_id, UpgradeId):
            return False
        return self.unit_type_id == unit_type_id

    def is_unit(self) -> bool:
        return self.unit_type_id in UnitTypes.TERRAN
    
    def get_unit_type_id(self) -> UnitTypeId | None:
        return self.unit_type_id
    
    def get_structure_being_built(self) -> Unit | None:
        return self.unit_being_built
    
    def set_unit_being_built(self, unit: Unit):
        self.unit_being_built = unit
        self.position = unit.position

    def get_position(self) -> Point2 | None:
        return self.position
    
    def is_same_structure(self, structure: Unit) -> bool:
        if self.unit_being_built and self.unit_being_built.tag == structure.tag:
            return True
        if self.position and self.bot.distance_math_hypot_squared(structure.position, self.position) < 2.25: # 1.5 squared
            return True
        return False
    
    def has_position_reserved(self) -> bool:
        return self.position is not None and self.unit_being_built is None
    
    def manhattan_distance(self, point: Point2) -> float:
        if self.position:
            return self.position.manhattan_distance(point)
        return 9999

    async def execute(self, special_locations: SpecialLocations, detected_enemy_builds: Dict[BuildType, float]) -> BuildResponseCode:
        response = await self.execute_facility_build()
        if response == BuildResponseCode.SUCCESS:
            self.is_in_progress = True
        return response

    @timed_async
    async def execute_facility_build(self) -> BuildResponseCode:
        response = None
        # not built by scv
        logger.debug(
            f"Trying to train unit {self.unit_type_id} with {self.builder_type}"
        )

        if self.unit_type_id in TECH_TREE:
            # check that all tech requirements are met
            for requirement in TECH_TREE[self.unit_type_id]:
                if self.bot.structure_type_build_progress(requirement) != 1:
                    return BuildResponseCode.NO_TECH
        if self.builder_type.intersection({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}):
            self.unit_in_charge = self.production.get_builder(self.unit_type_id)
            if self.unit_type_id in self.production.add_on_types and self.unit_in_charge:
                if self.interrupted_count > 5:
                    LogHelper.add_log(f"addon {self.unit_type_id} interrupted too many times ({self.interrupted_count}), setting addon blocked")
                    if await self.production.set_addon_blocked(self.unit_in_charge, self.interrupted_count):
                        self.interrupted_count = 0
                        self.unit_in_charge = None
                else:
                    self.position = self.unit_in_charge.add_on_position
        elif self.unit_type_id == UnitTypeId.SCV:
            # scv
            facility_candidates = self.bot.townhalls.filter(lambda x: x.is_ready and x.is_idle and not x.is_flying)
            facility_candidates.sort(key=lambda x: x.type_id == UnitTypeId.COMMANDCENTER)
            self.unit_in_charge = facility_candidates[0] if facility_candidates else None
        else:
            facility_candidates = self.bot.structures.filter(lambda x: x.type_id in self.builder_type and x.is_ready and x.is_idle and not x.is_flying)
            self.unit_in_charge = facility_candidates[0] if facility_candidates else None

        if self.unit_in_charge is None:
            logger.debug("no idle training facility")
            response = BuildResponseCode.NO_FACILITY
        else:
            if self.unit_type_id in {UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS}:
                self.unit_being_built = self.unit_in_charge
            # self.pos = self.unit_in_charge.position
            logger.debug(f"Found training facility {self.unit_in_charge}")
            build_response = self.unit_in_charge(self.get_build_ability())
            response = BuildResponseCode.SUCCESS if build_response else BuildResponseCode.FAILED
        return response

    def get_build_ability(self) -> AbilityId:
        if self.unit_type_id in {
            UnitTypeId.BARRACKSREACTOR,
            UnitTypeId.FACTORYREACTOR,
            UnitTypeId.STARPORTREACTOR,
        }:
            return AbilityId.BUILD_REACTOR
        if self.unit_type_id in {
            UnitTypeId.BARRACKSTECHLAB,
            UnitTypeId.FACTORYTECHLAB,
            UnitTypeId.STARPORTTECHLAB,
        }:
            return AbilityId.BUILD_TECHLAB
        return TRAIN_INFO[self.unit_in_charge.type_id][self.unit_type_id]["ability"] # type: ignore

    @timed_async
    async def is_interrupted(self) -> bool:
        if self.unit_in_charge is None:
            self.is_in_progress = False
            return True

        if self.unit_in_charge.is_idle:
            self.production.remove_type_from_facilty_queue(self.unit_in_charge, self.unit_type_id)
            self.is_in_progress = False
            return True
        return False

    def cancel_construction(self):
        logger.debug(f"canceling build of {self.unit_being_built}")
        if self.unit_being_built:
            self.unit_being_built(AbilityId.CANCEL_BUILDINPROGRESS)
        self.last_cancel_time = self.bot.time
        self.unit_being_built = None
        self.unit_in_charge = None
        self.position = None
        self.is_in_progress = False
        self.check_idle = False
        self.start_time = None
        self.completed_time = None
