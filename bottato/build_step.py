from loguru import logger
from typing import Optional, Union

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2, Point3
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO

from .mixins import UnitReferenceMixin
from bottato.economy.workers import Workers


class BuildStep(UnitReferenceMixin):
    supply_count: int
    unit_type_id: UnitTypeId
    unit_in_charge: Optional[Unit] = None
    unit_being_built: Optional[Unit] = None
    pos: Union[Unit, Point2]
    check_idle: bool = False

    def __init__(self, unit_type_id: UnitTypeId, bot: BotAI, workers: Workers = None):
        self.unit_type_id = unit_type_id
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.cost = bot.calculate_cost(unit_type_id)
        self.pos = None
        self.unit_in_charge: Unit = None
        self.completed_time: int = None

    def __repr__(self) -> str:
        unit_name = (
            self.unit_being_built.name
            if self.unit_being_built and self.unit_being_built is not True
            else self.unit_type_id
        )
        return f"BuildStep({unit_name}, {self.completed_time})"

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

    def refresh_worker_reference(self):
        logger.debug(f"unit in charge: {self.unit_in_charge}")
        try:
            self.unit_in_charge = self.get_updated_unit_reference(self.unit_in_charge)
        except self.UnitNotFound:
            self.unit_in_charge = None

    def get_builder_type(self, unit_type_id):
        if self.unit_type_id in {
            UnitTypeId.BARRACKSREACTOR,
            UnitTypeId.BARRACKSTECHLAB,
        }:
            return {UnitTypeId.BARRACKS}
        if self.unit_type_id in {UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB}:
            return {UnitTypeId.FACTORY}
        if self.unit_type_id in {
            UnitTypeId.STARPORTREACTOR,
            UnitTypeId.STARPORTTECHLAB,
        }:
            return {UnitTypeId.STARPORT}
        return UNIT_TRAINED_FROM[self.unit_type_id]

    async def execute(self, at_position: Point2 = None) -> bool:
        builder_type = self.get_builder_type(self.unit_type_id)
        if UnitTypeId.SCV in builder_type:
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
                    self.unit_in_charge = self.workers.get_builder(self.pos)
                    # self.unit_in_charge = self.bot.workers.filter(
                    #     lambda worker: worker.is_idle or worker.is_gathering
                    # ).closest_to(at_position)
                    logger.info(f"Found my builder {self.unit_in_charge}")
                    if self.unit_in_charge is None:
                        return False
                if self.unit_being_built is None:
                    build_response = self.unit_in_charge.build(
                        self.unit_type_id, at_position
                    )
                else:
                    build_response = self.unit_in_charge.smart(self.unit_being_built)
                logger.info(f"build_response: {build_response}")
                logger.info(f"Unit in charge is doing {self.unit_in_charge.orders}")

                if not build_response:
                    return False
        else:
            logger.info(
                f"Trying to train unit {self.unit_type_id} with {builder_type}"
            )
            # not built by scv
            try:
                self.unit_in_charge = self.bot.structures(builder_type).idle[0]
                logger.info(f"Found training facility {self.unit_in_charge}")
            except IndexError:
                # no available build structure
                return False
            build_ability: AbilityId = self.get_build_ability()
            self.unit_in_charge(build_ability)
            # self.unit_in_charge.train(self.unit_type_id)
            # PS: BotAI doesn't provide a callback method for `on_unit_create_started`
            self.unit_being_built = True
        self.draw_debug_box()
        self.is_in_progress = True
        return True

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
        logger.info(f"{self.unit_in_charge} is doing {self.unit_in_charge.orders}")
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
