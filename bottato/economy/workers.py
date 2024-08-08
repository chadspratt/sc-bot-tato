import math
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.constants import UnitTypeId
from sc2.position import Point2
from sc2.game_data import Cost

from ..mixins import UnitReferenceMixin, TimerMixin
from .minerals import Minerals
from .vespene import Vespene


class Workers(UnitReferenceMixin, TimerMixin):
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = -1000
        self.bot: BotAI = bot
        self.minerals = Minerals(bot)
        self.vespene = Vespene(bot)
        self.builders = Units([], bot)
        self.repairers = Units([], bot)
        self.known_worker_tags = []
        self.max_workers = 85
        self.health_per_repairer = 50
        self.max_repairers = 25

    def get_builder(self, building_position: Point2, needed_resources: Cost):
        builder = None
        logger.info(
            "selecting builder: "
            f"minerals_needed {needed_resources.minerals}, "
            f"vespene_needed {needed_resources.vespene}, "
            f"mineral_gatherers {self.minerals.worker_count}, "
            f"vespene_gatherers {self.vespene.worker_count}, "
            f"build position {building_position}"
        )
        if needed_resources.minerals > needed_resources.vespene and self.vespene.available_worker_count:
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
        self.start_timer("minerals.update_references")
        self.minerals.update_references()
        self.stop_timer("minerals.update_references")
        self.start_timer("vespene.update_references")
        self.vespene.update_references()
        self.stop_timer("vespene.update_references")
        self.start_timer("builders.update_references")
        self.builders = self.get_updated_unit_references(self.builders)
        self.stop_timer("builders.update_references")
        self.start_timer("repairers.update_references")
        self.repairers = self.get_updated_unit_references(self.repairers)
        self.stop_timer("repairers.update_references")

    def record_death(self, unit_tag):
        if unit_tag in self.known_worker_tags:
            self.known_worker_tags.remove(unit_tag)
            self.minerals.remove_worker_by_tag(unit_tag)
            self.vespene.remove_worker_by_tag(unit_tag)
        else:
            self.minerals.record_non_worker_death(unit_tag)

    def distribute_idle(self):
        if self.bot.workers.idle:
            logger.info(f"idle workers {self.bot.workers.idle}")
        workers_to_assign: set[int] = set(self.bot.workers.idle.tags)
        if len(self.bot.workers) != len(self.known_worker_tags):
            for worker in self.bot.workers:
                if worker.tag not in self.known_worker_tags:
                    self.known_worker_tags.append(worker.tag)
                    workers_to_assign.add(worker.tag)
        for worker in self.minerals.get_workers_from_depleted():
            workers_to_assign.add(worker.tag)

        if workers_to_assign:
            logger.info(f"idle or new workers {workers_to_assign}")
            for worker_tag in workers_to_assign:
                # try to remove first in case they were assigned to something despite being idle
                self.minerals.remove_worker_by_tag(worker_tag)
                self.vespene.remove_worker_by_tag(worker_tag)
                try:
                    worker = self.bot.workers.by_tag(worker_tag)
                except KeyError:
                    continue
                if self.minerals.has_unused_capacity:
                    logger.info(f"adding {worker_tag} to minerals")
                    self.minerals.add_worker(worker)
                    continue

                if self.vespene.has_unused_capacity:
                    logger.info(f"adding {worker_tag} to gas")
                    self.vespene.add_worker(worker)
                    continue

                # if self.minerals.add_long_distance_minerals(1) > 0:
                #     logger.info(f"adding {worker_tag} to long-distance")
                #     self.minerals.add_worker(worker)

        logger.info(
            f"[==WORKERS==] minerals({self.minerals.worker_count}), "
            f"vespene({self.vespene.worker_count}), "
            f"builders({len(self.builders)}), "
            f"repairers({len(self.repairers)}), "
            f"idle({len(self.bot.workers.idle)}), "
            f"total({len(self.bot.workers)})"
        )

    def units_needing_repair(self) -> Units:
        injured_mechanical_units = self.bot.units.filter(lambda unit: unit.is_mechanical
                                                         and unit.health < unit.health_max)
        logger.debug(f"injured mechanical units {injured_mechanical_units}")

        injured_structures = self.bot.structures.filter(lambda unit: unit.type_id != UnitTypeId.AUTOTURRET
                                                        and unit.build_progress == 1
                                                        and unit.health < unit.health_max)
        logger.debug(f"injured structures {injured_structures}")
        return injured_mechanical_units + injured_structures

    def repair_closest(self, injured_units: Units, repairer: Unit) -> bool:
        self_excluded = injured_units.filter(lambda unit: unit.tag != repairer.tag)
        if self_excluded:
            closest_injured = self_excluded.closest_to(repairer)
            repairer.repair(closest_injured)
            if closest_injured.tag not in self.bot.unit_tags_received_action:
                closest_injured.move(repairer)
            logger.info(f"{repairer} ordered to repair {closest_injured}")
            self.bot.client.debug_sphere_out(repairer, 1, (100, 255, 100))
            self.bot.client.debug_line_out(repairer, closest_injured, (100, 255, 100))
            return True
        return False

    async def redistribute_workers(self, needed_resources: Cost) -> int:
        injured_units = self.units_needing_repair()
        needed_repairers = 0
        missing_health = 0
        if injured_units:
            for unit in injured_units:
                missing_health += unit.health_max - unit.health
                logger.info(f"{unit} missing health {unit.health_max - unit.health}")
            needed_repairers = missing_health / self.health_per_repairer
            if needed_repairers > self.max_repairers:
                needed_repairers = self.max_repairers
            repairer_shortage = round(needed_repairers) - len(self.repairers)
            logger.info(f"missing health {missing_health} need repairers {needed_repairers} have {len(self.repairers)} shortage {repairer_shortage}")

            # remove excess repairers
            if repairer_shortage < 0:
                for i in range(-repairer_shortage):
                    retiring_repairer = self.repairers.furthest_to(injured_units.random)
                    if self.vespene.has_unused_capacity:
                        self.vespene.add_worker(retiring_repairer)
                        self.repairers.remove(retiring_repairer)
                        logger.info(f"{retiring_repairer} retiring to mine gas")
                    elif self.minerals.has_unused_capacity:
                        self.minerals.add_worker(retiring_repairer)
                        self.repairers.remove(retiring_repairer)
                        logger.info(f"{retiring_repairer} retiring to mine minerals")
                    else:
                        logger.info(f"nowhere for {retiring_repairer} to retire to, staying repairer")
                        break

            # tell existing to repair closest that isn't themself
            for repairer in self.repairers:
                self.repair_closest(injured_units, repairer)

            # add more repairers
            if repairer_shortage > 0:
                for i in range(repairer_shortage):
                    repairer: Unit = None
                    random_injured = injured_units.random
                    if needed_resources.minerals <= 0 or not self.vespene.assigned_workers:
                        repairer = self.minerals.take_worker_closest_to(random_injured.position)
                        logger.info(f"{repairer} repairer taken from minerals")
                    elif needed_resources.vespene <= 0 or not self.minerals.assigned_workers:
                        repairer = self.vespene.take_worker_closest_to(random_injured.position)
                        logger.info(f"{repairer} repairer taken from vespene")

                    if repairer:
                        self.repairers.append(repairer)
                        self.repair_closest(injured_units, repairer)
                    else:
                        break

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

    def get_mineral_capacity(self) -> int:
        return self.minerals.get_worker_capacity()
