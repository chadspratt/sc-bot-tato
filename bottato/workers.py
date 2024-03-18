from loguru import logger
from typing import List

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units

from .build_step import BuildStep
from .mixins import UnitReferenceMixin


class Workers(UnitReferenceMixin):
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = 0
        self.bot: BotAI = bot
        self.mineral_gatherers = Units([], bot)
        self.vespene_gatherers = Units([], bot)
        self.builders = Units([], bot)
        self.repairers = Units([], bot)
        self.known_townhall_tags = []
        self.mineral_fields = Units([], bot)
        # self.local_mineral_field_tags = []
        # self.local_vespene_field_tags = []
        self.vespene_fields = Units([], bot)
        self.worker_tags_by_mineral_field_tag = {}

    async def distribute_workers(self, pending_build_steps: List[BuildStep]):
        logger.info(
            f"workers: minerals({len(self.mineral_gatherers)}), "
            f"vespene({len(self.vespene_gatherers)}), "
            f"idle({len(self.bot.workers.idle)}), "
            f"total({len(self.bot.workers)})"
        )
        self.update_references()
        self.add_mineral_fields_for_townhalls()
        self.catalog_workers()
        self.distribute_idle()
        await self._distribute_workers(pending_build_steps)
        # await self.bot.distribute_workers()

    def catalog_workers(self):
        # put workers into correct bins (this may supercede `update_references`)
        self.mineral_gatherers = self.bot.workers.filter(
            lambda unit: unit.order_target in [m.tag for m in self.mineral_fields]
            or unit.is_carrying_minerals
        )
        self.vespene_gatherers = self.bot.workers.filter(
            lambda unit: unit.order_target
            in [v.tag for v in self.bot.gas_buildings.ready]
            or unit.is_carrying_vespene
        )
        self.repairers = self.bot.workers.filter(lambda unit: unit.is_repairing)
        # PS: This one is hard... maybe when we assign a worker to build
        #   something we could flag it? (with a little cross-talk between objects)
        # self.builders = self.bot.workers.filter(lambad unit: unit.is_using_ability())

    def update_references(self):
        # PS: we're getting fresh references for all SCVs from `catalog_workers`.
        # self.mineral_gatherers = self.get_updated_units_references(
        #     self.mineral_gatherers
        # )
        # logger.info(
        #     f"There are currently {len(self.mineral_gatherers)} mineral gatherers"
        # )
        # self.vespene_gatherers = self.get_updated_units_references(
        #     self.vespene_gatherers
        # )
        # logger.info(
        #     f"There are currently {len(self.vespene_gatherers)} vespene gatherers"
        # )
        self.builders = self.get_updated_units_references(self.builders)
        # self.repairers = self.get_updated_units_references(self.repairers)
        self.mineral_fields = self.get_updated_units_references(self.mineral_fields)

        # update mineral field worker counts
        current_worker_tags = [worker.tag for worker in self.mineral_gatherers]
        for worker_tags in self.worker_tags_by_mineral_field_tag.values():
            for worker_tag in worker_tags:
                if worker_tag not in current_worker_tags:
                    worker_tags.remove(worker_tag)

    def add_mineral_field_mapping(self, mineral_field: Unit, worker: Unit):
        self.worker_tags_by_mineral_field_tag[mineral_field.tag].append(worker.tag)

    def remove_mineral_field_mapping(self, worker: Unit):
        for worker_tags in self.worker_tags_by_mineral_field_tag.values():
            for worker_tag in worker_tags:
                if worker_tag == worker.tag:
                    worker_tags.remove(worker_tag)
                    return

    def needed_workers_for_minerals(self, mineral_field: Unit):
        return 2 - len(self.worker_tags_by_mineral_field_tag[mineral_field.tag])

    def add_mineral_fields_for_townhalls(self):
        for townhall in self.bot.townhalls.ready:
            if townhall.tag not in self.known_townhall_tags:
                for mineral in self.bot.mineral_field.closer_than(8, townhall):
                    self.mineral_fields.append(mineral)
                    # assuming no long-distance miners
                    self.worker_tags_by_mineral_field_tag[mineral.tag] = []
                self.known_townhall_tags.append(townhall.tag)

    def distribute_idle(self):
        if len(self.bot.workers.idle) == 0:
            return

        deficient_mineral_fields = self.mineral_fields.filter(
            lambda field: self.needed_workers_for_minerals(field) > 0
        )
        deficient_gas = self.bot.gas_buildings.ready.filter(
            lambda gas: gas.surplus_harvesters < 0
        )

        for worker in self.bot.workers.idle:
            nearest_mineral_field = deficient_mineral_fields.closest_to(worker)
            if nearest_mineral_field:
                worker.gather(nearest_mineral_field)
                self.worker_tags_by_mineral_field_tag[nearest_mineral_field.tag].append(
                    worker.tag
                )
                if self.needed_workers_for_minerals(nearest_mineral_field) == 0:
                    deficient_mineral_fields.remove(nearest_mineral_field)
                continue

            nearest_gas_building = deficient_gas.closest_to(worker)
            if nearest_gas_building:
                worker.smart(nearest_gas_building)
                # not sure how many it still needs so just add one and remove
                deficient_gas.remove(nearest_gas_building)
                continue

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

        # find first shortage
        for idx, build_step in enumerate(pending_build_steps):
            minerals_needed += build_step.cost.minerals
            vespene_needed += build_step.cost.vespene
            if minerals_needed > 0 or vespene_needed > 0:
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
            if workers_to_move > 1:
                if minerals_needed > vespene_needed:
                    # move workers to minerals
                    self.move_workers_to_minerals(workers_to_move)
                else:
                    # move workers to vespene
                    self.move_workers_to_vespene(workers_to_move)

    def move_workers_to_minerals(self, number_of_workers: int):
        workers_moved = 0

        for mineral_field in self.mineral_fields:
            needed_harvesters = self.needed_workers_for_minerals(mineral_field)
            if needed_harvesters < 0:
                # no space for more workers
                continue
            logger.info(
                f"need {needed_harvesters} mineral harvesters at {mineral_field}"
            )

            for worker in self.vespene_gatherers.closest_n_units(
                mineral_field, needed_harvesters
            ):
                logger.info("switching worker to minerals")
                worker.gather(mineral_field)

                self.mineral_gatherers.append(worker)
                self.vespene_gatherers.remove(worker)

                self.add_mineral_field_mapping(mineral_field, worker)

                self.last_worker_stop = self.bot.time
                workers_moved += 1
                if workers_moved == number_of_workers:
                    return
                continue

    def move_workers_to_vespene(self, number_to_move: int):
        workers_moved = 0

        for building in self.bot.gas_buildings.ready:
            needed_harvesters = -building.surplus_harvesters
            if needed_harvesters < 0:
                # no space for more workers
                continue
            logger.info(f"need {needed_harvesters} vespene harvesters at {building}")

            for worker in self.mineral_gatherers.closest_n_units(
                building, needed_harvesters
            ):
                logger.info("switching worker to vespene")
                worker.smart(building)

                self.vespene_gatherers.append(worker)
                self.mineral_gatherers.remove(worker)

                self.remove_mineral_field_mapping(worker)

                self.last_worker_stop = self.bot.time
                workers_moved += 1
                if workers_moved == number_to_move:
                    return
