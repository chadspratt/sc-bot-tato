import math
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from .mixins import UnitReferenceMixin


class Workers(UnitReferenceMixin):
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = 0
        self.bot: BotAI = bot
        self.minerals_needed = 0
        self.vespene_needed = 0
        self.mineral_gatherers = Units([], bot)
        self.vespene_gatherers = Units([], bot)
        self.builders = Units([], bot)
        self.repairers = Units([], bot)
        self.known_townhall_tags = []
        self.known_worker_tags = []
        self.mineral_fields = Units([], bot)
        self.vespene_fields = Units([], bot)
        self.worker_tags_by_mineral_field_tag = {}

    def get_builder(self, building_position: Point2):
        builder = None
        logger.info(f"minerals_needed {self.minerals_needed}, "
                    f"vespene_needed {self.vespene_needed}, "
                    f"mineral_gatherers {self.mineral_gatherers}, "
                    f"vespene_gatherers {self.vespene_gatherers}, "
                    f"build position {building_position}")
        if self.minerals_needed > self.vespene_needed and self.vespene_gatherers:
            builder = self.vespene_gatherers.closest_to(building_position)
            self.vespene_gatherers.remove(builder)
        elif self.mineral_gatherers:
            builder = self.mineral_gatherers.closest_to(building_position)
            self.remove_mineral_gatherer(builder)
        elif self.repairers:
            builder = self.repairers.closest_to(building_position)
            self.repairers.remove(builder)
        self.builders.append(builder)
        return builder

    async def distribute_workers(self):
        logger.info(
            f"workers: minerals({len(self.mineral_gatherers)}), "
            f"vespene({len(self.vespene_gatherers)}), "
            f"builders({len(self.builders)}), "
            f"repairers({len(self.repairers)}), "
            f"idle({len(self.bot.workers.idle)}), "
            f"total({len(self.bot.workers)})"
        )
        self.update_references()
        self.add_mineral_fields_for_townhalls()
        # self.catalog_workers()
        self.distribute_idle()
        await self.redistribute_workers()
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
        self.mineral_gatherers = self.get_updated_units_references(
            self.mineral_gatherers
        )
        self.vespene_gatherers = self.get_updated_units_references(
            self.vespene_gatherers
        )
        self.builders = self.get_updated_units_references(self.builders)
        self.repairers = self.get_updated_units_references(self.repairers)
        self.mineral_fields = self.get_updated_units_references(self.mineral_fields)

        # update mineral field worker counts
        current_worker_tags = [worker.tag for worker in self.mineral_gatherers]
        for worker_tags in self.worker_tags_by_mineral_field_tag.values():
            for worker_tag in worker_tags:
                if worker_tag not in current_worker_tags:
                    worker_tags.remove(worker_tag)

    def add_mineral_fields_for_townhalls(self):
        for townhall in self.bot.townhalls.ready:
            if townhall.tag not in self.known_townhall_tags:
                for mineral in self.bot.mineral_field.closer_than(8, townhall):
                    self.mineral_fields.append(mineral)
                    # assuming no long-distance miners
                    self.worker_tags_by_mineral_field_tag[mineral.tag] = []
                self.known_townhall_tags.append(townhall.tag)

    def distribute_idle(self):
        logger.info(f"idle workers {self.bot.workers.idle}")
        workers_to_assign = []
        if len(self.bot.workers) != len(self.known_worker_tags):
            for worker in self.bot.workers:
                if worker.tag not in self.known_worker_tags:
                    self.known_worker_tags.append(worker.tag)
                    workers_to_assign.append(worker)
        else:
            # maybe extraneous but could keep workers from slipping through cracks
            workers_to_assign = self.bot.workers.idle
        logger.info(f"idle or new workers {workers_to_assign}")
        if not workers_to_assign:
            return

        deficient_mineral_fields = self.mineral_fields.filter(
            lambda field: self.needed_workers_for_minerals(field) > 0
        )
        logger.info(f"deficient mineral fields {len(deficient_mineral_fields)}: {deficient_mineral_fields}")

        deficient_gas = self.bot.gas_buildings.ready.filter(
            lambda gas: gas.surplus_harvesters < 0
        )
        logger.info(f"deficient gas {len(deficient_gas)}: {deficient_gas}")

        for worker in workers_to_assign:
            nearest_mineral_field = deficient_mineral_fields.closest_to(worker)
            if nearest_mineral_field:
                self.assign_mineral_gatherer(worker, nearest_mineral_field)
                if self.needed_workers_for_minerals(nearest_mineral_field) == 0:
                    deficient_mineral_fields.remove(nearest_mineral_field)
                continue

            nearest_gas_building = deficient_gas.closest_to(worker)
            if nearest_gas_building:
                self.assign_vespene_gatherer(worker, nearest_mineral_field)
                # not sure how many it still needs so just add one and remove
                deficient_gas.remove(nearest_gas_building)
                continue

    def needed_workers_for_minerals(self, mineral_field: Unit):
        logger.info(f"mineral {mineral_field} has "
                    f"{len(self.worker_tags_by_mineral_field_tag[mineral_field.tag])}: "
                    f"{self.worker_tags_by_mineral_field_tag[mineral_field.tag]}")
        return 2 - len(self.worker_tags_by_mineral_field_tag[mineral_field.tag])

    def assign_mineral_gatherer(self, worker, mineral_field):
        logger.info(f"assigning worker {worker} to minerals {mineral_field}")
        worker.gather(mineral_field)
        self.worker_tags_by_mineral_field_tag[mineral_field.tag].append(
            worker.tag
        )
        self.mineral_gatherers.append(worker)

    def assign_vespene_gatherer(self, worker, gas_building):
        logger.info(f"assigning worker {worker} to gas {gas_building}")
        worker.smart(gas_building)
        self.vespene_gatherers.append(worker)

    async def redistribute_workers(self):
        cooldown = 3
        if self.bot.time - self.last_worker_stop <= cooldown:
            logger.info("Distribute workers is on cooldown")
            return

        max_workers_to_move = 10
        if self.minerals_needed <= 0:
            logger.info("saturate vespene")
            self.move_workers_to_vespene(max_workers_to_move)
        elif self.vespene_needed <= 0:
            logger.info("saturate minerals")
            self.move_workers_to_minerals(max_workers_to_move)
        else:
            # both positive
            workers_to_move = math.floor(abs(self.minerals_needed - self.vespene_needed) / 100.0)
            if workers_to_move > 0:
                if self.minerals_needed > self.vespene_needed:
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

            for worker in self.vespene_gatherers.closest_n_units(
                mineral_field, needed_harvesters
            ):
                self.assign_mineral_gatherer(worker, mineral_field)
                self.vespene_gatherers.remove(worker)

                self.last_worker_stop = self.bot.time
                workers_moved += 1
                if workers_moved == number_of_workers:
                    return

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
                self.assign_vespene_gatherer(worker, building)
                self.remove_mineral_gatherer(worker)

                self.last_worker_stop = self.bot.time
                workers_moved += 1
                if workers_moved == number_to_move:
                    return

    def remove_mineral_gatherer(self, worker: Unit):
        self.mineral_gatherers.remove(worker)
        for worker_tags in self.worker_tags_by_mineral_field_tag.values():
            for worker_tag in worker_tags:
                if worker_tag == worker.tag:
                    worker_tags.remove(worker_tag)
                    return
