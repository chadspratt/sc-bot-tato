from loguru import logger

from typing import Optional, Union
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM


class BuildStep:
    supply_count: int
    unit_type_id: UnitTypeId
    unit_in_charge: Optional[Unit] = None
    unit_being_built: Optional[Unit] = None
    pos: Union[Unit, Point2]

    def is_interrupted(self) -> bool:
        return self.unit_in_charge is None or self.unit_in_charge.health == 0 or self.unit_in_charge.is_idle or self.unit_in_charge.is_collecting

    def __init__(
        self,
        supply_count,
        unit_type_id,
        pos=None
    ):
        self.supply_count = supply_count
        self.unit_type_id = unit_type_id
        self.pos = pos

    def build_gas(self, bot: BotAI) -> bool:
        # All the vespene geysirs nearby, including ones with a refinery on top of it
        # command_centers = bot.townhalls
        vespene_geysirs = bot.vespene_geyser.in_distance_of_group(
            distance=10, other_units=bot.townhalls
        )
        for vespene_geysir in vespene_geysirs:
            if bot.gas_buildings.filter(lambda unit: unit.distance_to(vespene_geysir) < 1):
                continue
            # Select a worker closest to the vespene geysir
            self.unit_in_charge: Unit = bot.select_build_worker(vespene_geysir)
            
            # Worker can be none in cases where all workers are dead
            # or 'select_build_worker' function only selects from workers which carry no minerals
            if self.unit_in_charge is None:
                logger.info("No worker found for refinery build")
                return False
            # Issue the build command to the worker, important: vespene_geysir has to be a Unit, not a position
            self.unit_in_charge.build_gas(vespene_geysir)
            return True

    async def execute(self, bot: BotAI, at_position: Point2) -> bool:
        # logger.info("BuildStep.execute")
        if not bot.can_afford(self.unit_type_id):
            return False
        # get unit trained from (unit)
        # get unit ID -- builder type
        self.pos = at_position
        builder_type = UNIT_TRAINED_FROM[self.unit_type_id]
        if UnitTypeId.SCV in builder_type:
            logger.info(f"Trying to build structure {self.unit_type_id}")
            # this is a structure
            # TODO: Vespene targets unit to build instead of position
            if self.unit_type_id == UnitTypeId.REFINERY:
                self.build_gas(bot)
            else:
                if self.unit_in_charge is None or self.unit_in_charge.health == 0:
                    self.unit_in_charge = bot.workers.filter(
                        lambda worker: worker.is_collecting or worker.is_idle
                    ).closest_to(at_position)
                    logger.info(f"Found my builder {self.unit_in_charge}")
                if self.unit_being_built is None:
                    self.unit_in_charge.build(self.unit_type_id, at_position)
                else:
                    self.unit_in_charge.smart(self.unit_being_built)
        else:
            # this is a unit
            try:
                self.unit_in_charge = bot.structures(builder_type).idle[0]
            except IndexError:
                # no available build structure
                return False
            self.unit_in_charge.train(self.unit_type_id)
        self.is_in_progress = True
        return True

