import enum
from loguru import logger
from typing import Optional, Union

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.game_data import Cost

from .mixins import UnitReferenceMixin, GeometryMixin
from bottato.economy.workers import Workers
from bottato.economy.production import Production


class BuildStep(UnitReferenceMixin, GeometryMixin):
    supply_count: int
    unit_type_id: UnitTypeId = None
    upgrade_id: UpgradeId = None
    unit_in_charge: Optional[Unit] = None
    unit_being_built: Optional[Unit] = None
    pos: Union[Unit, Point2]
    check_idle: bool = False

    def __init__(self, unit_type: Union[UnitTypeId, UpgradeId], bot: BotAI, workers: Workers = None, production: Production = None):
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.production: Production = production
        self.unit_type_id = None
        self.cost = Cost(9999, 9999)
        # build cheapest option in set of unit_types
        if isinstance(unit_type, UnitTypeId):
            self.unit_type_id = unit_type
        else:
            self.upgrade_id = unit_type
        self.friendly_name = unit_type.name
        self.builder_type = self.production.get_builder_type(unit_type)
        self.cost = bot.calculate_cost(unit_type)

        self.pos = None
        self.unit_in_charge: Unit = None
        self.completed_time: int = None

    def __repr__(self) -> str:
        builder = self.unit_in_charge if self.unit_in_charge else self.builder_type
        # orders = self.unit_in_charge.orders if self.unit_in_charge else '[]'
        target = (
            f"{self.unit_being_built} {self.unit_being_built.build_progress}"
            if self.unit_being_built and self.unit_being_built is not True
            else self.unit_type_id
        )
        return f"{builder} has orders orders for target {target}"

    def draw_debug_box(self):
        if self.unit_in_charge is not None:
            self.bot.client.debug_sphere_out(self.unit_in_charge, 1, (255, 130, 0))
            if self.pos:
                self.bot.client.debug_line_out(self.unit_in_charge, self.convert_point2_to_3(self.pos), (255, 130, 0))
            self.bot.client.debug_text_world(
                str(self.unit_in_charge.tag), self.unit_in_charge.position3d)
        if self.pos:
            self.bot.client.debug_box2_out(self.convert_point2_to_3(self.pos), 0.5)
            self.bot.client.debug_text_world(
                self.unit_type_id.name, Point3((*self.pos, 10))
            )
        if self.unit_being_built is not None and self.unit_being_built is not True:
            logger.debug(f"unit being built {self.unit_being_built}")
            self.bot.client.debug_box2_out(self.unit_being_built, 0.75)

    def update_references(self):
        logger.debug(f"unit in charge: {self.unit_in_charge}")
        try:
            self.unit_in_charge = self.get_updated_unit_reference(self.unit_in_charge)
        except self.UnitNotFound:
            self.unit_in_charge = None
        if isinstance(self.unit_being_built, Unit):
            try:
                self.unit_being_built = self.get_updated_unit_reference(self.unit_being_built)
            except self.UnitNotFound:
                self.unit_being_built = None

    class ResponseCode(enum.Enum):
        SUCCESS = 0
        FAILED = 1
        NO_BUILDER = 2
        NO_FACILITY = 3
        NO_TECH = 4

    async def execute(self, at_position: Union[Point2, None] = None, needed_resources: Cost = None) -> ResponseCode:
        if self.upgrade_id:
            logger.info(f"researching upgrade {self.upgrade_id}")
            if self.unit_in_charge is None or self.unit_in_charge.health == 0:
                self.unit_in_charge = self.production.get_research_facility(self.upgrade_id)
                logger.info(f"research facility: {self.unit_in_charge}")
                if self.unit_in_charge is None:
                    return self.ResponseCode.NO_FACILITY
            successful_action: bool = self.bot.do(
                self.unit_in_charge.research(self.upgrade_id), subtract_cost=True, ignore_warning=True
            )
            if successful_action:
                return self.ResponseCode.SUCCESS
            return self.ResponseCode.FAILED
        elif UnitTypeId.SCV in self.builder_type:
            # this is a structure built by an scv
            if at_position is None:
                return False
            # Vespene targets unit to build instead of position
            empty_gas: Union[Unit, None] = None
            if self.unit_type_id == UnitTypeId.REFINERY:
                empty_gas = self.get_geysir()
                if empty_gas is None:
                    return self.ResponseCode.NO_FACILITY
                self.pos = empty_gas.position
            else:
                self.pos = at_position or self.pos
            logger.info(
                f"Trying to build structure {self.unit_type_id} at {self.pos}"
            )
            if self.unit_in_charge is None or self.unit_in_charge.health == 0:
                self.unit_in_charge = self.workers.get_builder(self.pos, needed_resources)
                if self.unit_in_charge is None:
                    return self.ResponseCode.NO_BUILDER
                logger.info(f"{self.unit_type_id} found builder {self.unit_in_charge}")
                self.unit_in_charge.move(self.pos)
            if self.unit_type_id == UnitTypeId.REFINERY:
                self.unit_in_charge.build_gas(empty_gas)
            elif self.unit_being_built is None:
                build_response = self.unit_in_charge.build(
                    self.unit_type_id, at_position
                )
                if self.unit_type_id in {UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS}:
                    self.unit_being_built = self.unit_in_charge
                if not build_response:
                    return self.ResponseCode.FAILED
            else:
                build_response = self.unit_in_charge.smart(self.unit_being_built)
                logger.info(f"{self.unit_in_charge} in charge is doing {self.unit_in_charge.orders}")

                if not build_response:
                    return self.ResponseCode.FAILED
        else:
            # not built by scv
            logger.info(
                f"Trying to train unit {self.unit_type_id} with {self.builder_type}"
            )
            if self.builder_type.intersection({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}):
                self.unit_in_charge = self.production.get_builder(self.unit_type_id)
                if self.unit_in_charge is None:
                    logger.debug("no idle training facility")
                    return self.ResponseCode.NO_FACILITY
            else:
                try:
                    facility_candidates = self.bot.structures(self.builder_type)
                    logger.info(f"training facility candidates {facility_candidates}")
                    for facility in facility_candidates:
                        logger.info(f"{facility}, ready={facility.is_ready}, idle={facility.is_idle}, orders={facility.orders}")
                    self.unit_in_charge = facility_candidates.ready.idle[0]
                except IndexError:
                    # no available build structure
                    logger.debug("no idle training facility")
                    return self.ResponseCode.NO_FACILITY
            self.pos = self.unit_in_charge.position
            logger.info(f"Found training facility {self.unit_in_charge}")
            build_ability: AbilityId = self.get_build_ability()
            self.unit_in_charge(build_ability)
            # self.unit_in_charge.train(self.unit_type_id)
            # PS: BotAI doesn't provide a callback method for `on_unit_create_started`
            self.unit_being_built = True
        self.draw_debug_box()
        self.is_in_progress = True
        return self.ResponseCode.SUCCESS

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
        return TRAIN_INFO[self.unit_in_charge.type_id][self.unit_type_id]["ability"]

    def get_geysir(self) -> Union[Unit, None]:
        # All the vespene geysirs nearby, including ones with a refinery on top of it
        # command_centers = bot.townhalls
        vespene_geysirs = self.bot.vespene_geyser.in_distance_of_group(
            distance=10, other_units=self.bot.townhalls
        )
        for vespene_geysir in vespene_geysirs:
            if self.bot.gas_buildings.filter(
                lambda unit: unit.distance_to(vespene_geysir) < 1
            ):
                continue
            return vespene_geysir
        return None

    def is_interrupted(self) -> bool:
        if self.unit_in_charge is None:
            logger.info(f"{self} builder is missing")
            return True

        self.check_idle: bool = self.check_idle or (
            self.unit_in_charge.is_active and not self.unit_in_charge.is_gathering
        )

        if self.check_idle:
            if self.unit_in_charge.is_idle:
                logger.info(f"unit_in_charge {self.unit_in_charge}")
                return True
        return False
