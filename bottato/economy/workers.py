import math
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.position import Point2
from sc2.game_data import Cost

from ..mixins import UnitReferenceMixin
from .minerals import Minerals
from .vespene import Vespene


class Workers(UnitReferenceMixin):
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = -1000
        self.bot: BotAI = bot
        self.minerals = Minerals(bot)
        self.vespene = Vespene(bot)
        self.minerals_needed = 0
        self.vespene_needed = 0
        self.builders = Units([], bot)
        self.repairers = Units([], bot)
        self.known_worker_tags = []

    def get_builder(self, building_position: Point2):
        builder = None
        logger.info(
            f"minerals_needed {self.minerals_needed}, "
            f"vespene_needed {self.vespene_needed}, "
            f"mineral_gatherers {self.minerals.worker_count}, "
            f"vespene_gatherers {self.vespene.worker_count}, "
            f"build position {building_position}"
        )
        if self.minerals_needed > self.vespene_needed and self.vespene.available_worker_count:
            builder = self.vespene.take_worker_closest_to(building_position)
        elif self.minerals.worker_count:
            builder = self.minerals.take_worker_closest_to(building_position)
        elif self.repairers:
            builder = self.repairers.closest_to(building_position)
            self.repairers.remove(builder)
        else:
            logger.info("FAILED TO GET BUILDER")
        if builder is not None:
            self.builders.append(builder)
        return builder

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
        self.minerals.update_references()
        self.vespene.update_references()
        self.builders = self.get_updated_unit_references(self.builders)
        self.repairers = self.get_updated_unit_references(self.repairers)

    def distribute_idle(self):
        if self.bot.workers.idle:
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

        if workers_to_assign:
            logger.info(f"idle or new workers {workers_to_assign}")
            for worker in workers_to_assign:
                if self.minerals.has_unused_capacity:
                    self.minerals.add_worker(worker)
                    continue

                if self.vespene.has_unused_capacity:
                    self.vespene.add_worker(worker)

        logger.info(
            f"workers: minerals({self.minerals.worker_count}), "
            f"vespene({self.vespene.worker_count}), "
            f"builders({len(self.builders)}), "
            f"repairers({len(self.repairers)}), "
            f"idle({len(self.bot.workers.idle)}), "
            f"total({len(self.bot.workers)})"
        )

    async def redistribute_workers(self, needed_resources: Cost) -> int:
        remaining_cooldown = 3 - (self.bot.time - self.last_worker_stop)
        if remaining_cooldown > 0:
            logger.info(f"Distribute workers is on cooldown for {remaining_cooldown}")
            return -1

        max_workers_to_move = 10
        if needed_resources.minerals <= 0:
            logger.info("saturate vespene")
            return self.move_workers_to_vespene(max_workers_to_move)
        if needed_resources.vespene <= 0:
            logger.info("saturate minerals")
            return self.move_workers_to_minerals(max_workers_to_move)

        # both positive
        workers_to_move = math.floor(
            abs(needed_resources.minerals - needed_resources.vespene) / 100.0
        )
        if workers_to_move > 0:
            if needed_resources.minerals > needed_resources.vespene:
                # move workers to minerals
                return self.move_workers_to_minerals(workers_to_move)

            # move workers to vespene
            return self.move_workers_to_vespene(workers_to_move)

    def move_workers_to_minerals(self, number_to_move: int) -> int:
        number_moved = self.minerals.transfer_workers_from(self.vespene, number_to_move)
        if number_moved > 0:
            self.last_worker_stop = self.bot.time
        return number_moved

    def move_workers_to_vespene(self, number_to_move: int) -> int:
        number_moved = self.vespene.transfer_workers_from(self.minerals, number_to_move)
        if number_moved > 0:
            self.last_worker_stop = self.bot.time
        return number_moved
