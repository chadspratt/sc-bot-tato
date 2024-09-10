import math
import enum
from loguru import logger
from typing import Union

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.constants import UnitTypeId, AbilityId
from sc2.position import Point2
from sc2.game_data import Cost

from ..mixins import UnitReferenceMixin, TimerMixin
from .minerals import Minerals
from .vespene import Vespene
from .resources import Resources


class JobType(enum.Enum):
    IDLE = 0
    MINERALS = 1
    VESPENE = 2
    BUILD = 3
    REPAIR = 4
    ATTACK = 5


class WorkerAssignment():
    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.job_type: JobType = JobType.IDLE
        self.target: Unit = None
        self.unit_available: bool = True
        self.gather_position: Point2 = None
        self.last_stop: Point2 = None
        self.dropoff_position: Point2 = None
        self.returning: bool = False

    def __repr__(self) -> str:
        return f"WorkerAssignment({self.unit}({self.unit_available}), {self.job_type.name}, {self.target})"


class Workers(UnitReferenceMixin, TimerMixin):
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = -1000
        self.bot: BotAI = bot
        self.assignments_by_worker: dict[int, WorkerAssignment] = {}
        self.assignments_by_job: dict[JobType, list[WorkerAssignment]] = {
            JobType.IDLE: [],
            JobType.MINERALS: [],
            JobType.VESPENE: [],
            JobType.BUILD: [],
            JobType.REPAIR: [],
            JobType.ATTACK: [],
        }
        self.minerals = Minerals(bot)
        self.vespene = Vespene(bot)
        self.max_workers = 75
        self.health_per_repairer = 50
        self.max_repairers = 25
        for worker in self.bot.workers:
            self.add_worker(worker)

    def add_worker(self, worker: Unit) -> bool:
        if worker.tag not in self.assignments_by_worker:
            new_assignment = WorkerAssignment(worker)
            self.assignments_by_worker[worker.tag] = new_assignment
            self.assignments_by_job[JobType.IDLE].append(new_assignment)
            return True
        return False

    def update_references(self):
        self.start_timer("minerals.update_references")
        self.minerals.update_references()
        self.stop_timer("minerals.update_references")
        self.start_timer("vespene.update_references")
        self.vespene.update_references()
        self.stop_timer("vespene.update_references")

        self.assignments_by_job[JobType.IDLE].clear()
        self.assignments_by_job[JobType.MINERALS].clear()
        self.assignments_by_job[JobType.VESPENE].clear()
        self.assignments_by_job[JobType.BUILD].clear()
        self.assignments_by_job[JobType.REPAIR].clear()
        self.assignments_by_job[JobType.ATTACK].clear()
        for assignment in self.assignments_by_worker.values():
            try:
                assignment.unit = self.get_updated_unit_reference(assignment.unit)
                assignment.unit_available = True
            except UnitReferenceMixin.UnitNotFound:
                assignment.unit_available = False
                logger.info(f"{assignment.unit} unavailable, maybe already working on {assignment.target}")
            if assignment.job_type in self.assignments_by_job:
                self.assignments_by_job[assignment.job_type].append(assignment)
            else:
                self.assignments_by_job[assignment.job_type] = [assignment]
        logger.debug(f"assignment summary {self.assignments_by_job}")

    def speed_mine(self):
        for assignment in self.assignments_by_worker.values():
            if assignment.unit_available and assignment.job_type in [JobType.MINERALS]:
                worker: Unit = assignment.unit
                if not worker.is_moving:
                    assignment.last_stop = worker.position
                if worker.is_carrying_resource:
                    if not assignment.returning:
                        assignment.returning = True
                        # if assignment.target.distance_to(assignment.last_stop) < assignment.target.radius + 0.1:
                        #     assignment.gather_position = assignment.last_stop
                    if len(worker.orders) == 1:
                        # might be none ready if converting first cc to orbital
                        candidates: Units = self.bot.townhalls.ready or self.bot.townhalls
                        dropoff: Unit = candidates.closest_to(worker)
                        self.speed_smart(worker, dropoff, assignment.dropoff_position)
                else:
                    assignment.returning = False
                    if len(worker.orders) == 1 and assignment.target:
                        self.speed_smart(worker, assignment.target, assignment.gather_position)

    def speed_smart(self, worker: Unit, target: Unit, position: Union[Point2, None]) -> None:
        if position is None:
            position: Point2 = target.position
            min_distance = target.radius + worker.radius
            position = position.towards(worker, min_distance, limit=True)
        remaining_distance = worker.distance_to(position)
        if remaining_distance > 2:
            worker(AbilityId.SMART, target)
        elif remaining_distance < 0.2:
            pass
        else:
            worker.move(position)
            worker(AbilityId.SMART, target, True)

    def attack_nearby_enemies(self) -> None:
        for assignment in self.assignments_by_worker.values():
            reference_unit: Unit = assignment.target or self.bot.townhalls.closest_to(assignment.unit.position)
            if self.bot.enemy_units and reference_unit:
                nearest_enemy = self.bot.enemy_units.closest_to(reference_unit.position)
                if nearest_enemy.distance_to(reference_unit.position) < 10:
                    logger.info(f"worker {assignment.unit} attacking enemy to defend {reference_unit} which is maybe {assignment.target}")
                    assignment.unit.attack(nearest_enemy)

    def update_assigment(self, worker: Unit, new_job: JobType, new_target: Union[Unit, None]):
        self.update_job(worker, new_job)
        self.update_target(worker, new_target)

    def update_job(self, worker: Unit, new_job: JobType):
        assignment = self.assignments_by_worker[worker.tag]
        logger.info(f"worker {worker} changing from {assignment.job_type} to {new_job}")
        if assignment.job_type == JobType.MINERALS:
            self.minerals.remove_worker(worker)
        elif assignment.job_type == JobType.VESPENE:
            self.vespene.remove_worker(worker)
        self.assignments_by_job[assignment.job_type].remove(assignment)
        assignment.job_type = new_job
        self.assignments_by_job[new_job].append(assignment)

    def update_target(self, worker: Unit, new_target: Union[Unit, None]):
        if worker.tag not in self.assignments_by_worker:
            return
        assignment = self.assignments_by_worker[worker.tag]
        logger.debug(f"worker {worker} changing from {assignment.target} to {new_target}")
        if new_target:
            if assignment.job_type == JobType.REPAIR:
                worker.repair(new_target)
                if new_target.tag not in self.bot.unit_tags_received_action:
                    new_target.move(worker)
            elif assignment.job_type == JobType.VESPENE:
                self.vespene.add_worker_to_node(worker, new_target)
                worker.smart(new_target)
            elif assignment.job_type == JobType.MINERALS:
                self.minerals.add_worker_to_node(worker, new_target)
                worker.gather(new_target)
            else:
                worker.smart(new_target)
        else:
            if assignment.job_type == JobType.MINERALS:
                new_target = self.minerals.add_worker(worker)
            elif assignment.job_type == JobType.VESPENE:
                new_target = self.vespene.add_worker(worker)
            worker.smart(new_target)
        assignment.target = new_target
        assignment.gather_position = None

    def record_death(self, unit_tag):
        if unit_tag in self.assignments_by_worker:
            del self.assignments_by_worker[unit_tag]
            # assign_by_job should be cleaned up by update_references refresh
            self.minerals.remove_worker_by_tag(unit_tag)
            self.vespene.remove_worker_by_tag(unit_tag)
        else:
            self.minerals.record_non_worker_death(unit_tag)

    def get_builder(self, building_position: Point2, needed_resources: Cost):
        builder = None
        candidates: Units = (
            self.availiable_workers_on_job(JobType.IDLE)
            or self.availiable_workers_on_job(JobType.VESPENE)
            or self.availiable_workers_on_job(JobType.MINERALS)
            or self.availiable_workers_on_job(JobType.REPAIR)
        )
        if not candidates:
            logger.info("FAILED TO GET BUILDER")
        else:
            builder = candidates.closest_to(building_position)
            if builder is not None:
                self.update_assigment(builder, JobType.BUILD, None)
                logger.info(f"found builder {builder}")

        return builder

    def availiable_workers_on_job(self, job_type: JobType) -> Units:
        return Units([
            assignment.unit for assignment in self.assignments_by_job[job_type] if assignment.unit_available],
            bot_object=self.bot)

    def deliver_resources(self, worker: Unit):
        if worker.is_carrying_resource:
            nearest_cc = self.bot.townhalls.ready.closest_to(worker)
            worker.smart(nearest_cc)
            logger.info(f"{worker} delivering resources to {nearest_cc}")

    def set_as_idle(self, worker: Unit):
        self.update_assigment(worker, JobType.IDLE, None)

    def distribute_idle(self):
        if self.bot.workers.idle:
            logger.info(f"idle workers {self.bot.workers.idle}")
        for worker in self.bot.workers.idle:
            assigment: WorkerAssignment = self.assignments_by_worker[worker.tag]
            if assigment.job_type != JobType.BUILD:
                self.update_job(worker, JobType.IDLE)
        for worker in self.minerals.get_workers_from_depleted():
            self.update_job(worker, JobType.IDLE)

        idle_workers: Units = self.availiable_workers_on_job(JobType.IDLE)
        if idle_workers:
            logger.info(f"idle or new workers {idle_workers}")
            for worker in idle_workers:
                if self.minerals.has_unused_capacity:
                    logger.info(f"adding {worker.tag} to minerals")
                    self.update_assigment(worker, JobType.MINERALS, None)
                    continue

                if self.vespene.has_unused_capacity:
                    logger.info(f"adding {worker.tag} to gas")
                    self.update_assigment(worker, JobType.VESPENE, None)
                    continue

                # if self.minerals.add_long_distance_minerals(1) > 0:
                #     logger.info(f"adding {worker.tag} to long-distance")
                #     self.minerals.add_worker(worker)

        logger.info(
            f"[==WORKERS==] minerals({len(self.assignments_by_job[JobType.MINERALS])}), "
            f"vespene({len(self.assignments_by_job[JobType.VESPENE])}), "
            f"builders({len(self.assignments_by_job[JobType.BUILD])}), "
            f"repairers({len(self.assignments_by_job[JobType.REPAIR])}), "
            f"idle({len(self.assignments_by_job[JobType.IDLE])}({len(self.bot.workers.idle)})), "
            f"total({len(self.assignments_by_worker.keys())}({len(self.bot.workers)}))"
        )

    async def redistribute_workers(self, needed_resources: Cost) -> int:
        self.update_repairers(needed_resources)

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
        return 0

    def update_repairers(self, needed_resources: Cost) -> None:
        injured_units = self.units_needing_repair()
        needed_repairers: int = 0
        missing_health = 0
        # limit to percentage of total workers
        max_repairers = min(self.max_repairers, math.floor(len(self.bot.workers) / 2))
        if injured_units:
            for unit in injured_units:
                missing_health += unit.health_max - unit.health
                logger.info(f"{unit} missing health {unit.health_max - unit.health}")
            needed_repairers = missing_health / self.health_per_repairer
            if needed_repairers > max_repairers:
                needed_repairers = max_repairers

        current_repairers: Units = self.availiable_workers_on_job(JobType.REPAIR)
        repairer_shortage: int = round(needed_repairers) - len(current_repairers)
        logger.info(f"missing health {missing_health} need repairers {needed_repairers} have {len(current_repairers)} shortage {repairer_shortage}")

        # remove excess repairers
        if repairer_shortage < 0:
            for i in range(-repairer_shortage):
                retiring_repairer = current_repairers.furthest_to(injured_units.random) if injured_units else current_repairers.random
                if self.vespene.has_unused_capacity:
                    self.update_assigment(retiring_repairer, JobType.VESPENE, None)
                elif self.minerals.has_unused_capacity:
                    self.update_assigment(retiring_repairer, JobType.MINERALS, None)
                else:
                    logger.info(f"nowhere for {retiring_repairer} to retire to, staying repairer")
                    break
                current_repairers.remove(retiring_repairer)

        # tell existing to repair closest that isn't themself
        for repairer in current_repairers:
            self.update_target(repairer, self.get_repair_target(repairer, injured_units))

        # add more repairers
        if repairer_shortage > 0:
            candidates: Units = None
            if needed_resources.minerals <= 0 or not self.availiable_workers_on_job(JobType.VESPENE):
                candidates = self.availiable_workers_on_job(JobType.MINERALS)
            elif needed_resources.vespene <= 0 or not self.availiable_workers_on_job(JobType.MINERALS):
                candidates = self.availiable_workers_on_job(JobType.VESPENE)
            for i in range(repairer_shortage):
                if not candidates:
                    break
                random_injured = injured_units.random
                repairer: Unit = candidates.closest_to(random_injured)
                candidates.remove(repairer)

                if repairer:
                    self_excluded = injured_units.filter(lambda unit: unit.tag != repairer.tag)
                    new_target: Unit = None
                    if self_excluded:
                        new_target = self_excluded.closest_to(repairer)
                    self.update_assigment(repairer, JobType.REPAIR, new_target)
                else:
                    break

    def get_repair_target(self, repairer: Unit, injured_units: Units) -> Unit:
        self_excluded = injured_units.filter(lambda unit: unit.tag != repairer.tag)
        new_target: Unit = None
        if self_excluded:
            new_target = self_excluded.closest_to(repairer)
        return new_target

    def units_needing_repair(self) -> Units:
        injured_mechanical_units = self.bot.units.filter(lambda unit: unit.is_mechanical
                                                         and unit.health < unit.health_max)
        logger.debug(f"injured mechanical units {injured_mechanical_units}")

        injured_structures = self.bot.structures.filter(lambda unit: unit.type_id != UnitTypeId.AUTOTURRET
                                                        and unit.build_progress == 1
                                                        and unit.health < unit.health_max)
        logger.debug(f"injured structures {injured_structures}")
        return injured_mechanical_units + injured_structures

    def move_workers_to_minerals(self, number_to_move: int) -> int:
        self.move_workers_between_resources(self.vespene, self.minerals, JobType.MINERALS, number_to_move)

    def move_workers_to_vespene(self, number_to_move: int) -> int:
        self.move_workers_between_resources(self.minerals, self.vespene, JobType.VESPENE, number_to_move)

    def move_workers_between_resources(self, source: Resources, target: Resources, target_job: JobType, number_to_move: int) -> int:
        moved_count = 0
        mineral_nodes = target.nodes_with_capacity()
        if not mineral_nodes:
            return 0

        candidates: Units = None
        if target_job == JobType.VESPENE:
            candidates = self.availiable_workers_on_job(JobType.MINERALS)
        else:
            candidates = self.availiable_workers_on_job(JobType.VESPENE)
        # logger.info(f"candidates to move to {target_job}: {candidates}")

        next_node: Unit = mineral_nodes.pop()
        while moved_count < number_to_move and candidates and target.has_unused_capacity:
            if target.needed_workers_for_node(next_node) == 0:
                if mineral_nodes:
                    next_node = mineral_nodes.pop()
                    continue
                break
            worker = candidates.closest_to(next_node)
            candidates.remove(worker)
            self.update_assigment(worker, target_job, next_node)
            moved_count += 1

        if moved_count:
            self.last_worker_stop = self.bot.time
        return moved_count

    def get_mineral_capacity(self) -> int:
        return self.minerals.get_worker_capacity()
