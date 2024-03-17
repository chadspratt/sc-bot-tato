from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units

from .build_step import BuildStep


class Workers:
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = 0
        self.bot: BotAI = bot

    async def distribute_workers(self, pending_build_steps: list[BuildStep]):
        await self._distribute_workers(pending_build_steps)
        await self.bot.distribute_workers()
        logger.info(
            [worker.order_target for worker in self.bot.workers if worker.order_target]
        )

    async def _distribute_workers(self, pending_build_steps: list[BuildStep]):
        max_workers_to_move = 10
        if not pending_build_steps:
            return
        cooldown = 3
        if self.bot.time - self.last_worker_stop <= cooldown:
            logger.info("Distribute workers is on cooldown")
            return
        minerals_needed = -self.bot.minerals
        vespene_needed = -self.bot.vespene

        for idx, build_step in enumerate(pending_build_steps):
            # how much _more_ do we need for the next three steps of each resource
            minerals_needed += build_step.cost.minerals
            vespene_needed += build_step.cost.vespene
            if idx > 2 and (minerals_needed > 0 or vespene_needed > 0):
                break
        logger.info(
            f"next {idx} builds need {vespene_needed} vespene, {minerals_needed} minerals"
        )

        if minerals_needed <= 0:
            logger.info("saturate vespene")
            self.move_workers_to_vespene(max_workers_to_move)
        elif vespene_needed <= 0:
            logger.info("saturate minerals")
            self.move_workers_to_minerals(max_workers_to_move)
        else:
            # both positive
            workers_to_move = abs(minerals_needed - vespene_needed) / 100.0
            if workers_to_move > 2:
                if minerals_needed > vespene_needed:
                    # move workers to minerals
                    self.move_workers_to_minerals(workers_to_move)
                else:
                    # move workers to vespene
                    self.move_workers_to_vespene(workers_to_move)

    def move_workers_to_vespene(self, number_of_workers: int):
        workers_moved = 0
        for building in self.bot.gas_buildings.ready:
            needed_harvesters = -building.surplus_harvesters
            if needed_harvesters < 0:
                # no space for more workers
                continue
            logger.info(f"need {needed_harvesters} vespene harvesters at {building}")
            gatherers = self.get_mineral_gatherers_near_building(
                building, needed_harvesters
            )
            if gatherers is not None:
                for gatherer in gatherers:
                    logger.info("switching worker to vespene")
                    gatherer.smart(building)
                    self.last_worker_stop = self.bot.time
                    workers_moved += 1
                    if workers_moved >= number_of_workers:
                        return

    def move_workers_to_minerals(self, number_of_workers: int):
        workers_moved = 0
        for building in self.bot.townhalls.ready:
            needed_harvesters = -building.surplus_harvesters
            if needed_harvesters < 0:
                # no space for more workers
                continue
            logger.info(f"need {needed_harvesters} mineral harvesters at {building}")

            local_minerals = {
                mineral
                for mineral in self.bot.mineral_field
                if mineral.distance_to(building) <= 12
            }
            target_mineral = max(
                local_minerals,
                key=lambda mineral: mineral.mineral_contents,
                default=None,
            )
            logger.info(f"target mineral patch {target_mineral}")

            if target_mineral:
                gatherers = self.get_vespene_gatherers_near_building(
                    building, needed_harvesters
                )
                if gatherers is not None:
                    for gatherer in gatherers:
                        logger.info("switching worker to minerals")
                        gatherer.gather(target_mineral)
                        self.last_worker_stop = self.bot.time
                        workers_moved += 1
                        if workers_moved >= number_of_workers:
                            return

    def get_mineral_gatherers_near_building(
        self, for_building: Unit, count: int
    ) -> Units:
        if not self.bot.workers:
            return None
        local_minerals_tags = {
            mineral.tag
            for mineral in self.bot.mineral_field
            if mineral.distance_to(for_building) <= 12
        }
        return self.bot.workers.filter(
            lambda unit: unit.order_target in local_minerals_tags
            and not unit.is_carrying_minerals
        ).closest_n_units(for_building, count)

    def get_vespene_gatherers_near_building(
        self, for_building: Unit, count: int
    ) -> Units:
        if not self.bot.workers:
            return None
        gas_building_tags = [b.tag for b in self.bot.gas_buildings.ready]
        vespene_workers = self.bot.workers.filter(
            lambda unit: unit.order_target in gas_building_tags
            and not unit.is_carrying_vespene
        )
        if vespene_workers:
            return vespene_workers.closest_n_units(for_building, count)
