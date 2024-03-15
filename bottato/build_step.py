from loguru import logger

from typing import Optional, Union
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO


class BuildStep:
    supply_count: int
    unit_type_id: UnitTypeId
    unit_in_charge: Optional[Unit] = None
    unit_being_built: Optional[Unit] = None
    pos: Union[Unit, Point2]
    check_idle: bool = False

    def __init__(
        self,
        bot: BotAI,
        unit_type_id: UnitTypeId,
    ):
        self.unit_type_id = unit_type_id
        self.bot: BotAI = bot
        self.cost = bot.calculate_cost(unit_type_id)
        self.pos = None
        self.unit_in_charge: Unit = None

    def __repr__(self) -> str:
        return f"BuildStep({self.unit_type_id}, {self.unit_in_charge}, {self.unit_being_built}, {self.pos})"

    async def execute(self, at_position: Point2) -> bool:
        self.pos = at_position
        builder_type = UNIT_TRAINED_FROM[self.unit_type_id]
        if UnitTypeId.SCV in builder_type:
            # this is a structure built by an scv
            logger.info(f"Trying to build structure {self.unit_type_id}")
            # Vespene targets unit to build instead of position
            if self.unit_type_id == UnitTypeId.REFINERY:
                self.build_gas()
            else:
                if self.unit_in_charge is None or self.unit_in_charge.health == 0:
                    self.unit_in_charge = self.bot.workers.filter(
                        lambda worker: worker.is_collecting or worker.is_idle
                    ).closest_to(at_position)
                    logger.info(f"Found my builder {self.unit_in_charge}")
                if self.unit_being_built is None:
                    self.unit_in_charge.build(self.unit_type_id, at_position)
                else:
                    self.unit_in_charge.smart(self.unit_being_built)
        else:
            # not built by scv
            try:
                self.unit_in_charge = self.bot.structures(builder_type).idle[0]
            except IndexError:
                # no available build structure
                return False
            build_ability: AbilityId = TRAIN_INFO[self.unit_in_charge.type_id][
                self.unit_type_id
            ]["ability"]
            self.unit_in_charge(build_ability)
            # self.unit_in_charge.train(self.unit_type_id)
        self.is_in_progress = True
        return True

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
                logger.info("No worker found for refinery build")
                return False
            # Issue the build command to the worker, important: vespene_geysir has to be a Unit, not a position
            self.unit_in_charge.build_gas(vespene_geysir)
            return True

    def is_interrupted(self) -> bool:
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
                    f"unit_in_charge.is_collecting {self.unit_in_charge.is_collecting}"
                )
                logger.info(
                    f"unit_in_charge.is_gathering {self.unit_in_charge.is_gathering}"
                )
            return True
