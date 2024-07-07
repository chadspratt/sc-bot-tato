import enum
from loguru import logger
from typing import Optional, Union, Iterable

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2, Point3
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.game_data import Cost

from .mixins import UnitReferenceMixin
from bottato.economy.workers import Workers
from bottato.economy.production import Production


class BuildStep(UnitReferenceMixin):
    supply_count: int
    unit_type_id: UnitTypeId
    unit_in_charge: Optional[Unit] = None
    unit_being_built: Optional[Unit] = None
    pos: Union[Unit, Point2]
    check_idle: bool = False

    def __init__(self, unit_types: Union[UnitTypeId, Iterable[UnitTypeId]], bot: BotAI, workers: Workers = None, production: Production = None):
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.production: Production = production
        self.unit_type_id = None
        self.cost = Cost(9999, 9999)
        # build cheapest option in set of unit_types
        if isinstance(unit_types, UnitTypeId):
            self.unit_type_id = unit_types
            self.cost = bot.calculate_cost(unit_types)
        else:
            for unit_type in unit_types:
                unit_cost = bot.calculate_cost(unit_type)
                if unit_cost.minerals + unit_cost.vespene < self.cost.minerals + self.cost.vespene:
                    self.unit_type_id = unit_type
                    self.cost = unit_cost
        self.builder_type = self.production.get_builder_type(self.unit_type_id)
        self.pos = None
        self.unit_in_charge: Unit = None
        self.completed_time: int = None

    def __repr__(self) -> str:
        builder = self.unit_in_charge if self.unit_in_charge else self.builder_type
        orders = self.unit_in_charge.orders if self.unit_in_charge else '[]'
        target = (
            f"{self.unit_being_built} {self.unit_being_built.build_progress}"
            if self.unit_being_built and self.unit_being_built is not True
            else self.unit_type_id
        )
        return f"{builder} has orders {orders} for target {target}"

    def draw_debug_box(self):
        if self.unit_in_charge is not None:
            self.bot.client.debug_sphere_out(self.unit_in_charge, 1)
            self.bot.client.debug_text_world(
                str(self.unit_in_charge.tag), self.unit_in_charge.position3d)
        if self.pos is not None:
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

    async def execute(self, at_position: Point2 = None, needed_resources: Cost = None) -> ResponseCode:
        if UnitTypeId.SCV in self.builder_type:
            if at_position is None:
                return False
            # this is a structure built by an scv
            logger.info(
                f"Trying to build structure {self.unit_type_id} at {at_position}"
            )
            # Vespene targets unit to build instead of position
            if self.unit_type_id == UnitTypeId.REFINERY:
                self.build_gas()
            else:
                self.pos = at_position or self.pos
                if self.unit_in_charge is None or self.unit_in_charge.health == 0:
                    self.unit_in_charge = self.workers.get_builder(self.pos, needed_resources)
                    # self.unit_in_charge = self.bot.workers.filter(
                    #     lambda worker: worker.is_idle or worker.is_gathering
                    # ).closest_to(at_position)
                    if self.unit_in_charge is None:
                        return self.ResponseCode.NO_BUILDER
                    logger.info(f"Found my builder {self.unit_in_charge}")
                if self.unit_being_built is None:
                    build_response = self.unit_in_charge.build(
                        self.unit_type_id, at_position
                    )
                else:
                    build_response = self.unit_in_charge.smart(self.unit_being_built)
                logger.info(f"Unit in charge is doing {self.unit_in_charge.orders}")

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
                    logger.info("no idle training facility")
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
                    logger.info("no idle training facility")
                    return self.ResponseCode.NO_FACILITY
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

    def build_gas(self) -> bool:
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
            # Select a worker closest to the vespene geysir
            self.unit_in_charge: Unit = self.bot.select_build_worker(vespene_geysir)

            # Worker can be none in cases where all workers are dead
            # or 'select_build_worker' function only selects from workers which carry no minerals
            if self.unit_in_charge is None:
                logger.debug("No worker found for refinery build")
                return False
            # Issue the build command to the worker, important: vespene_geysir has to be a Unit, not a position
            self.unit_in_charge.build_gas(vespene_geysir)
            return True

    def is_interrupted(self) -> bool:
        if self.unit_in_charge is None:
            return True
        logger.debug(f"{self}")

        self.check_idle: bool = self.check_idle or (
            self.unit_in_charge.is_active and not self.unit_in_charge.is_gathering
        )
        builder_is_missing = (
            self.unit_in_charge is None or self.unit_in_charge.health == 0
        )
        builder_is_distracted = (
            self.unit_in_charge.is_idle or self.unit_in_charge.is_gathering
        )
        if builder_is_missing or (self.check_idle and builder_is_distracted):
            logger.info(f"unit_in_charge {self.unit_in_charge}")
            if self.unit_in_charge is not None:
                logger.info(f"unit_in_charge.health {self.unit_in_charge.health}")
                logger.info(f"unit_in_charge.is_idle {self.unit_in_charge.is_idle}")
                logger.info(
                    f"unit_in_charge.is_gathering {self.unit_in_charge.is_gathering}"
                )
                logger.info(
                    f"unit_in_charge.is_collecting {self.unit_in_charge.is_collecting}"
                )
            return True
