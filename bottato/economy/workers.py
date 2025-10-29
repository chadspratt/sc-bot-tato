import math
import enum
from loguru import logger
from typing import Union

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.constants import UnitTypeId, AbilityId
from sc2.position import Point2, Point3
from sc2.game_data import Cost

from bottato.map.map import Map
from bottato.micro.micro_factory import MicroFactory
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.enemy import Enemy
from bottato.mixins import GeometryMixin, UnitReferenceMixin, TimerMixin
from bottato.economy.minerals import Minerals
from bottato.economy.vespene import Vespene
from bottato.economy.resources import Resources


class JobType(enum.Enum):
    IDLE = 0
    MINERALS = 1
    VESPENE = 2
    BUILD = 3
    REPAIR = 4
    ATTACK = 5
    SCOUT = 6


class WorkerAssignment():
    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.job_type: JobType = JobType.IDLE
        self.target: Unit = None
        self.unit_available: bool = True
        self.gather_position: Point2 = None
        self.dropoff_target: Unit = None
        self.dropoff_position: Point2 = None
        self.initial_gather_complete: bool = False
        self.is_returning = False
        self.on_attack_break = False
        self.attack_target_tag: int = None

    def __repr__(self) -> str:
        return f"WorkerAssignment({self.unit}({self.unit_available}), {self.job_type.name}, {self.target})"


class Workers(UnitReferenceMixin, TimerMixin, GeometryMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map) -> None:
        self.bot: BotAI = bot
        self.enemy = enemy
        self.map = map
        self.last_worker_stop = -1000
        self.assignments_by_worker: dict[int, WorkerAssignment] = {}
        self.assignments_by_job: dict[JobType, list[WorkerAssignment]] = {
            JobType.IDLE: [],
            JobType.MINERALS: [],
            JobType.VESPENE: [],
            JobType.BUILD: [],
            JobType.REPAIR: [],
            JobType.ATTACK: [],
            JobType.SCOUT: [],
        }
        self.minerals = Minerals(bot, self.map)
        self.vespene = Vespene(bot)
        self.max_workers = 75
        self.health_per_repairer = 50
        self.max_repairers = 10
        self.mule_energy_threshold = 50
        for worker in self.bot.workers:
            self.add_worker(worker)
        self.aged_mules: Units = Units([], bot)
        self.worker_micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.bot.workers.first, self.bot, self.enemy)
        self.units_to_attack = set()

    def update_references(self, units_by_tag: dict[int, Unit], builder_tags: list[int]):
        self.start_timer("update_references")
        self.minerals.update_references(units_by_tag)
        self.vespene.update_references(units_by_tag)

        self.assignments_by_job[JobType.IDLE].clear()
        self.assignments_by_job[JobType.MINERALS].clear()
        self.assignments_by_job[JobType.VESPENE].clear()
        self.assignments_by_job[JobType.BUILD].clear()
        self.assignments_by_job[JobType.REPAIR].clear()
        self.assignments_by_job[JobType.ATTACK].clear()
        self.assignments_by_job[JobType.SCOUT].clear()
        for assignment in self.assignments_by_worker.values():
            try:
                assignment.unit = self.get_updated_unit_reference(assignment.unit, units_by_tag)
                assignment.unit_available = True
            except UnitReferenceMixin.UnitNotFound:
                # unit is inside a structure
                assignment.unit_available = False

            try:
                assignment.target = self.get_updated_unit_reference(assignment.target, units_by_tag)
            except UnitReferenceMixin.UnitNotFound:
                assignment.target = None

            try:
                assignment.dropoff_target = self.get_updated_unit_reference(assignment.dropoff_target, units_by_tag)
            except UnitReferenceMixin.UnitNotFound:
                assignment.dropoff_target = None
                assignment.dropoff_position = None

            if assignment.unit_available:
                # keep workers in sync with build steps, minerals, and vespene
                if assignment.unit.tag in builder_tags:
                    assignment.job_type = JobType.BUILD
                elif assignment.job_type == JobType.BUILD:
                    assignment.job_type = JobType.IDLE
                elif assignment.job_type == JobType.MINERALS:
                    resource_node = self.minerals.get_node_by_worker_tag(assignment.unit.tag)
                    if resource_node:
                        assignment.target = resource_node.node
                    else:
                        assignment.target = None
                        assignment.unit(AbilityId.HALT)
                        assignment.job_type = JobType.IDLE
                elif assignment.job_type == JobType.VESPENE:
                    resource_node = self.vespene.get_node_by_worker_tag(assignment.unit.tag)
                    if resource_node:
                        assignment.target = resource_node.node
                    else:
                        assignment.target = None
                        assignment.unit(AbilityId.HALT)
                        assignment.job_type = JobType.IDLE

                if assignment.job_type != JobType.VESPENE:
                    self.vespene.remove_worker_by_tag(assignment.unit.tag)
                if assignment.job_type != JobType.MINERALS:
                    self.minerals.remove_worker_by_tag(assignment.unit.tag)

            self.assignments_by_job[assignment.job_type].append(assignment)
            self.bot.client.debug_text_3d(f"{assignment.job_type.name}\n{assignment.unit.tag}",
                                          assignment.unit.position3d + Point3((0, 0, 1)), size=8, color=(255, 255, 255))
        logger.debug(f"assignment summary {self.assignments_by_job}")
        self.stop_timer("update_references")

    def add_worker(self, worker: Unit) -> bool:
        if worker.tag not in self.assignments_by_worker:
            new_assignment = WorkerAssignment(worker)
            self.assignments_by_worker[worker.tag] = new_assignment
            self.assignments_by_job[JobType.IDLE].append(new_assignment)
            if worker.type_id == UnitTypeId.MULE:
                self.minerals.update_references(None)
                self.aged_mules.append(worker)
                closest_minerals: Unit = self.closest_unit_to_unit(worker, self.minerals.nodes_with_mule_capacity())
                if closest_minerals is None:
                    self.update_assigment(worker, JobType.IDLE, None)
                else:
                    self.update_assigment(worker, JobType.MINERALS, closest_minerals)
                    self.minerals.add_mule(worker, closest_minerals)
                    logger.debug(f"added mule {worker.tag}({worker.position}) to minerals {closest_minerals}({closest_minerals.position})")
            return True
        return False

    def drop_mules(self):
        self.start_timer("my_workers.drop_mules")
        # take off mules that are about to expire so they don't waste minerals
        for mule in self.aged_mules.copy():
            if mule.age > 58:
                try:
                    updated_mule = self.bot.units.by_tag(mule.tag)
                    if not updated_mule.is_carrying_resource:
                        updated_mule.move(self.bot.enemy_start_locations[0])
                        self.remove_mule(mule)
                        self.update_assigment(updated_mule, JobType.IDLE, None)
                except KeyError:
                    self.remove_mule(mule)

        for orbital in self.bot.townhalls(UnitTypeId.ORBITALCOMMAND):
            if orbital.energy < self.mule_energy_threshold:
                continue
            mineral_fields: Units = self.minerals.nodes_with_mule_capacity()
            if mineral_fields:
                fullest_mineral_field: Unit = max(mineral_fields, key=lambda x: x.mineral_contents)
                nearest_townhall: Unit = self.bot.townhalls.closest_to(fullest_mineral_field)
                orbital(AbilityId.CALLDOWNMULE_CALLDOWNMULE, target=fullest_mineral_field.position.towards(nearest_townhall), queue=True)
        self.stop_timer("my_workers.drop_mules")

    def remove_mule(self, mule):
        logger.debug(f"removing mule {mule}")
        self.minerals.remove_mule(mule)
        self.aged_mules.remove(mule)

    async def speed_mine(self):
        self.start_timer("my_workers.speed_mine")
        assignment: WorkerAssignment
        for assignment in self.assignments_by_worker.values():
            if assignment.on_attack_break \
                    or not assignment.unit_available \
                    or assignment.job_type not in [JobType.MINERALS, JobType.VESPENE] \
                    or await self.worker_micro.retreat(assignment.unit, 1.0):
                continue
            
            if not self.bot.townhalls.ready:
                logger.warning(
                    f"{self.bot.time_formatted} Attempting to speed mine with no townhalls"
                )
                break

            if not self.bot.mineral_field:
                logger.warning(
                    f"{self.bot.time_formatted} Attempting to speed mine with no mineral fields"
                )
                break

            # self.bottato_speed_mine(assignment)
            self.ares_speed_mine(assignment)
            # self.sharpy_speed_mine(assignment)
        self.stop_timer("my_workers.speed_mine")

    def sharpy_speed_mine(self, assignment: WorkerAssignment) -> None:
        worker = assignment.unit
        townhall = self.bot.townhalls.closest_to(worker)

        if worker.is_returning and len(worker.orders) == 1:
            target: Point2 = townhall.position
            target = target.towards(worker, townhall.radius + worker.radius)
            if 0.75 < worker.distance_to(target) < 2:
                worker.move(target)
                worker(AbilityId.SMART, townhall, True)
                return

        if (
            not worker.is_returning
            and len(worker.orders) == 1
            and isinstance(worker.order_target, int)
        ):
            # mf = self.cache.by_tag(worker.order_target)
            mf = assignment.target
            if mf is not None and mf.is_mineral_field:
                # target = self.mineral_target_dict.get(mf.position)
                target = assignment.gather_position
                worker_distance = worker.distance_to(target)
                if target and 0.75 < worker_distance < 2:
                    worker.move(target)
                    worker(AbilityId.SMART, mf, True)
                elif worker_distance <= 0.75:
                    first_order = worker.orders[0]
                    if first_order.ability.id != AbilityId.HARVEST_GATHER or first_order.target != assignment.target.tag:
                        worker(AbilityId.SMART, assignment.target)

    TOWNHALL_RADIUS: float = 2.75
    DISTANCE_TO_TOWNHALL_FACTOR: float = 1.08
    def ares_speed_mine(self, assignment: WorkerAssignment) -> bool:
        worker = assignment.unit
        len_orders: int = len(worker.orders)

        # do some further processing here or the orders
        # but in general if worker has 2 orders it is speedmining
        if len_orders == 2:
            return True

        if (worker.is_returning or worker.is_carrying_resource) and len_orders < 2:
            if assignment.dropoff_target and assignment.dropoff_target.is_flying:
                # can't dropoff to a flying cc
                assignment.dropoff_target = None
                assignment.dropoff_position = None
            if assignment.dropoff_target is None:
                non_flying = self.bot.townhalls.ready.filter(lambda th: not th.is_flying)
                if non_flying:
                    closest_townhall: Unit = self.closest_unit_to_unit(worker, non_flying)
                    if closest_townhall.distance_to(worker) < 15:
                        assignment.dropoff_target = closest_townhall
                if assignment.dropoff_target is None:
                    return False

            target_pos: Point2 = assignment.dropoff_target.position

            target_pos: Point2 = Point2(
                target_pos.towards(worker, self.TOWNHALL_RADIUS * self.DISTANCE_TO_TOWNHALL_FACTOR)
            )

            if 0.5625 < worker.distance_to_squared(target_pos) < 4.0:
                worker.move(target_pos)
                worker(AbilityId.SMART, assignment.dropoff_target, True)
                return True
            # not at right distance to get boost command, but doesn't have return
            # resource command for some reason
            elif not worker.is_returning:
                worker(AbilityId.SMART, assignment.dropoff_target)
                return True

        elif not worker.is_returning and len_orders < 2:
            min_distance: float = 0.5625 if assignment.target.is_mineral_field else 0.01
            max_distance: float = 4.0 if assignment.target.is_mineral_field else 0.25
            worker_distance: float = worker.distance_to_squared(assignment.gather_position) if assignment.gather_position else math.inf
            if (
                min_distance
                < worker_distance
                < max_distance
                or worker.is_idle
            ):
                worker.move(assignment.gather_position)
                worker(AbilityId.SMART, assignment.target, True)
                return True
            else:
                first_order = worker.orders[0]
                if first_order.ability.id != AbilityId.HARVEST_GATHER or first_order.target != assignment.target.tag:
                    worker(AbilityId.SMART, assignment.target)
                    return True

        # on rare occasion above conditions don't hit and worker goes idle
        elif worker.is_idle or not worker.is_moving:
            if worker.is_carrying_resource:
                worker.return_resource()
            else:
                worker.gather(assignment.target)
            return True

        return False

    def bottato_speed_mine(self, assignment: WorkerAssignment) -> None:
        worker = assignment.unit
        if worker.is_carrying_resource:
            self.start_timer("my_workers.speed_mine returning")
            assignment.initial_gather_complete = True
            assignment.is_returning = True
            if len(worker.orders) == 1:
                if assignment.dropoff_target is None:
                    # might be none ready if converting first cc to orbital
                    dropoff_candidates: Units = self.bot.townhalls.ready or self.bot.townhalls
                    if dropoff_candidates:
                        assignment.dropoff_target = dropoff_candidates.closest_to(worker)
                        min_distance = assignment.dropoff_target.radius + worker.radius
                        position = assignment.dropoff_target.position.towards(worker, min_distance, limit=True)
                        assignment.dropoff_position = position
                self.speed_smart(worker, assignment.dropoff_target, assignment.dropoff_position)
            self.stop_timer("my_workers.speed_mine returning")
        elif assignment.target:
            self.start_timer("my_workers.speed_mine gathering")
            if assignment.initial_gather_complete:
                if assignment.gather_position is None:
                    assignment.gather_position = self.minerals.nodes_by_tag[assignment.target.tag].mining_position
                if assignment.is_returning:
                    assignment.is_returning = False
                    worker.move(assignment.gather_position)
                elif len(worker.orders) == 1 and assignment.target:
                    self.speed_smart(worker, assignment.target, assignment.gather_position)
            else:
                # first time gathering, just gather
                worker.gather(assignment.target)
            self.stop_timer("my_workers.speed_mine gathering")

    def speed_smart(self, worker: Unit, target: Unit, position: Union[Point2, None] = None) -> None:
        self.start_timer("my_workers.speed_smart")
        if position is None:
            return
        remaining_distance = worker.distance_to(position)
        if 0.75 < remaining_distance < 1.75:
            worker.move(position)
            worker(AbilityId.SMART, target, True)
        elif remaining_distance <= 0.75:
            first_order = worker.orders[0]
            if first_order.ability.id != AbilityId.HARVEST_GATHER or first_order.target != target.tag:
                worker(AbilityId.SMART, target)
        self.stop_timer("my_workers.speed_smart")

    async def attack_nearby_enemies(self) -> None:
        self.start_timer("my_workers.attack_nearby_enemies")
        attacker_tags = set()
        if self.bot.townhalls:
            available_workers = self.bot.workers.filter(lambda u: self.assignments_by_worker[u.tag].job_type in {JobType.MINERALS, JobType.VESPENE})
            healthy_workers = available_workers.filter(lambda u: u.health_percentage > 0.5)
            unhealthy_workers = available_workers.filter(lambda u: u.health_percentage <= 0.5)

            for townhall in self.bot.townhalls:
                nearby_enemy_structures = self.bot.enemy_structures.closer_than(20, townhall).filter(lambda u: not u.is_flying and u.can_be_attacked)
                if nearby_enemy_structures:
                    nearby_enemy_structures.sort(key=lambda a: (a.type_id != UnitTypeId.PHOTONCANNON) * 10000 + a.distance_to(townhall))
                nearby_enemy_range = 25 if nearby_enemy_structures else 12
                nearby_enemies = self.bot.enemy_units.closer_than(nearby_enemy_range, townhall).filter(lambda u: not u.is_flying and u.can_be_attacked)
                enemies_to_remove = []
                for enemy in self.units_to_attack:
                    predicted_position = self.enemy.get_predicted_position(enemy, 0.0)
                    if predicted_position is None:
                        enemies_to_remove.append(enemy)
                    elif predicted_position.distance_to(townhall.position) < 25:
                        nearby_enemies.append(enemy)
                for enemy in enemies_to_remove:
                    self.units_to_attack.remove(enemy)

                if len(nearby_enemies) >= len(available_workers):
                    # don't suicide workers if outnumbered
                    continue
                # assign closest 3 workers to attack each enemy
                micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.bot.workers.first, self.bot, self.enemy)
                workers_per_enemy_unit = 2 if nearby_enemy_structures else 3
                for nearby_enemy in nearby_enemies + nearby_enemy_structures:
                    enemy_position = nearby_enemy if nearby_enemy.age == 0 else self.enemy.get_predicted_position(nearby_enemy, 0.0)
                    attackers = []
                    number_of_attackers = 4 if nearby_enemy.is_structure else workers_per_enemy_unit
                    if len(healthy_workers) > number_of_attackers:
                        attackers = healthy_workers.closest_n_units(enemy_position, number_of_attackers)
                        for attacker in attackers:
                            healthy_workers.remove(attacker)
                    else:
                        attackers = [worker for worker in healthy_workers]
                        healthy_workers.clear()
                        if unhealthy_workers:
                            remainder = number_of_attackers - len(healthy_workers)

                            if len(unhealthy_workers) > remainder:
                                unhealthy_attackers = unhealthy_workers.closest_n_units(enemy_position, remainder)
                                for attacker in unhealthy_attackers:
                                    unhealthy_workers.remove(attacker)
                                attackers.extend(unhealthy_attackers)
                            else:
                                attackers.extend([worker for worker in unhealthy_workers])
                                unhealthy_workers.clear()
                    if not attackers:
                        break
                    for attacker in attackers:
                        max_attack_distance = 20 if nearby_enemy.is_structure else 15
                        if attacker.distance_to(enemy_position) > max_attack_distance:
                            # don't pull workers from far away
                            continue
                        if nearby_enemy.is_structure:
                            attacker.attack(nearby_enemy)
                        elif nearby_enemy.age == 0:
                            await micro.move(attacker, nearby_enemy.position)
                        else:
                            await micro.move(attacker, enemy_position)
                        attacker_tags.add(attacker.tag)
                        self.assignments_by_worker[attacker.tag].on_attack_break = True
        # put any leftover workers back to work
        for worker in self.bot.workers:
            assignment = self.assignments_by_worker[worker.tag]
            if assignment.on_attack_break and worker.tag not in attacker_tags:
                assignment.on_attack_break = False
                if assignment.target:
                    if assignment.unit.is_carrying_resource and self.bot.townhalls:
                        assignment.unit.smart(self.bot.townhalls.closest_to(assignment.unit))
                    else:
                        assignment.unit.smart(assignment.target)

        self.stop_timer("my_workers.attack_nearby_enemies")

    def attack_enemy(self, enemy: Unit):
        for existing_enemy in self.units_to_attack:
            if existing_enemy.tag == enemy.tag:
                self.units_to_attack.remove(existing_enemy)
                logger.debug(f"updated enemy to attack {enemy}")
                break
        logger.debug(f"added enemy to attack {enemy}")
        self.units_to_attack.add(enemy)

    def update_assigment(self, worker: Unit, job_type: JobType, target: Union[Unit, None]):
        self.update_job(worker, job_type)
        if not self.update_target(worker, target):
            self.update_job(worker, JobType.REPAIR)
            self.update_target(worker)

    def update_job(self, worker: Unit, new_job: JobType):
        if worker.tag not in self.assignments_by_worker:
            return
        assignment = self.assignments_by_worker[worker.tag]
        if assignment.job_type == new_job:
            return

        if assignment.job_type == JobType.MINERALS:
            self.minerals.remove_worker(worker)
        elif assignment.job_type == JobType.VESPENE:
            self.vespene.remove_worker(worker)

        self.assignments_by_job[assignment.job_type].remove(assignment)
        assignment.job_type = new_job
        self.assignments_by_job[new_job].append(assignment)

    def update_target(self, worker: Unit, new_target: Union[Unit, None] = None) -> bool:
        if worker.tag not in self.assignments_by_worker:
            return
        assignment = self.assignments_by_worker[worker.tag]
        logger.debug(f"worker {worker} changing from {assignment.target} to {new_target}")
        if new_target:
            if assignment.job_type == JobType.REPAIR:
                if new_target.tag not in self.bot.unit_tags_received_action:
                    if new_target.type_id != UnitTypeId.SCV or self.assignments_by_worker[new_target.tag].job_type != JobType.REPAIR:
                        # don't move if the scv is already repairing something else
                        new_target.move(worker)
                # if not self.bot.enemy_units or self.bot.time < 360 or self.closest_distance(new_target, self.bot.enemy_units) > 5:
                    # worker.repair(new_target)
            elif assignment.job_type == JobType.VESPENE:
                if self.vespene.add_worker_to_node(worker, new_target):
                    assignment.gather_position = new_target.position
                    if worker.is_carrying_resource and self.bot.townhalls:
                        worker.smart(self.bot.townhalls.closest_to(worker))
                    else:
                        worker.smart(new_target)
                else:
                    return False
            elif assignment.job_type == JobType.MINERALS:
                if self.minerals.add_worker_to_node(worker, new_target):
                    assignment.gather_position = self.minerals.nodes_by_tag[new_target.tag].mining_position
                    assignment.dropoff_target = None
                    assignment.dropoff_position = None
                    if worker.is_carrying_resource and self.bot.townhalls:
                        worker.smart(self.bot.townhalls.closest_to(worker))
                    else:
                        # worker.move(assignment.gather_position)
                        worker.gather(new_target)
                else:
                    return False
            else:
                worker.smart(new_target)
        else:
            if assignment.job_type == JobType.REPAIR:
                injured_units = self.units_needing_repair().filter(lambda u: u.tag != worker.tag)
                if injured_units:
                    new_target = injured_units.closest_to(worker)
                    if new_target.tag not in self.bot.unit_tags_received_action:
                        if new_target.type_id != UnitTypeId.SCV or self.assignments_by_worker[new_target.tag].job_type != JobType.REPAIR:
                            # don't move if the scv is already repairing something else
                            new_target.move(worker)
                    # worker.repair(new_target)
                else:
                    return False
            elif assignment.job_type == JobType.MINERALS:
                new_target = self.minerals.add_worker(worker)
                if new_target is None:
                    # No capacity available, keep worker idle
                    logger.warning(f"No mineral capacity for worker {worker}, keeping idle")
                    return False
                assignment.gather_position = self.minerals.nodes_by_tag[new_target.tag].mining_position
                assignment.dropoff_target = None
                assignment.dropoff_position = None
                if worker.is_carrying_resource and self.bot.townhalls:
                    # worker.move(assignment.dropoff_position)
                    worker.smart(self.bot.townhalls.closest_to(worker))
                else:
                    # worker.move(assignment.gather_position)
                    worker.smart(new_target)
            elif assignment.job_type == JobType.VESPENE:
                new_target = self.vespene.add_worker(worker)
                if new_target is None:
                    # No capacity available, keep worker idle
                    logger.warning(f"No vespene capacity for worker {worker}, keeping idle")
                    return False
                if worker.is_carrying_resource and self.bot.townhalls:
                    worker.smart(self.bot.townhalls.closest_to(worker))
                else:
                    worker.smart(new_target)
        if assignment.target != new_target:
            assignment.initial_gather_complete = False
        assignment.target = new_target
        return True
        # assignment.gather_position = None

    def record_death(self, unit_tag):
        if unit_tag in self.assignments_by_worker:
            del self.assignments_by_worker[unit_tag]
            # assign_by_job should be cleaned up by update_references refresh
            self.minerals.remove_worker_by_tag(unit_tag)
            self.vespene.remove_worker_by_tag(unit_tag)
        else:
            self.minerals.record_non_worker_death(unit_tag)

    def get_builder(self, building_position: Point2):
        builder = None
        candidates: Units = (
            self.availiable_workers_on_job(JobType.IDLE)
            + self.availiable_workers_on_job(JobType.VESPENE)
            + self.availiable_workers_on_job(JobType.MINERALS)
            # + self.availiable_workers_on_job(JobType.REPAIR)
        )
        if not candidates:
            logger.debug("FAILED TO GET BUILDER")
        else:
            builder = candidates.closest_to(building_position)
            if builder is not None:
                logger.debug(f"found builder {builder}")
                self.update_assigment(builder, JobType.BUILD, None)

        return builder

    def get_scout(self, position: Point2) -> Union[Unit, None]:
        scout: Unit = None
        candidates: Units = (
            self.availiable_workers_on_job(JobType.IDLE)
            or self.availiable_workers_on_job(JobType.VESPENE)
            or self.availiable_workers_on_job(JobType.MINERALS)
            or self.availiable_workers_on_job(JobType.REPAIR)
        )
        if not candidates:
            logger.debug("FAILED TO GET SCOUT")
        else:
            scout = candidates.closest_to(position)
            if scout is not None:
                logger.debug(f"found scout {scout}")
                self.update_assigment(scout, JobType.SCOUT, None)

        return scout

    def availiable_workers_on_job(self, job_type: JobType) -> Units:
        return Units([
            assignment.unit for assignment in self.assignments_by_job[job_type]
            if assignment.unit_available
                and assignment.unit.type_id != UnitTypeId.MULE
                and not (assignment.job_type in (JobType.MINERALS, JobType.VESPENE) and assignment.unit.is_carrying_resource)
                and not assignment.on_attack_break
        ],
            bot_object=self.bot)

    # def deliver_resources(self, worker: Unit):
    #     if worker.is_carrying_resource:

    def set_as_idle(self, worker: Unit):
        if worker.tag in self.assignments_by_worker:
            self.update_assigment(worker, JobType.IDLE, None)

    builder_idle_time: dict[int, int] = {}
    def distribute_idle(self):
        self.start_timer("my_workers.distribute_idle")
        if self.bot.workers.idle:
            logger.debug(f"idle workers {self.bot.workers.idle}")
        tags_to_remove = [tag for tag in self.builder_idle_time if tag not in self.bot.workers.idle.tags]
        for tag in tags_to_remove:
            del self.builder_idle_time[tag]
        for worker in self.bot.workers.idle:
            assigment: WorkerAssignment = self.assignments_by_worker[worker.tag]
            if assigment.unit.type_id == UnitTypeId.MULE:
                continue
            elif assigment.job_type == JobType.BUILD and (not assigment.target or not assigment.target.is_ready):
                if worker.tag not in self.builder_idle_time:
                    self.builder_idle_time[worker.tag] = self.bot.time
                    continue
                elif self.bot.time - self.builder_idle_time[worker.tag] < 5:
                    # wait up to 5 seconds before determining worker is idle
                    continue
                else:
                    del self.builder_idle_time[worker.tag]
            elif assigment.job_type == JobType.SCOUT:
                continue
            elif assigment.job_type == JobType.IDLE:
                continue
            self.set_as_idle(worker)
        for worker in self.minerals.get_workers_from_depleted() + self.vespene.get_workers_from_depleted():
            self.set_as_idle(worker)
        for worker in self.minerals.get_workers_from_overcapacity():
            self.set_as_idle(worker)

        idle_workers: Units = self.availiable_workers_on_job(JobType.IDLE)
        idle_count = len(idle_workers)
        reassigned_count = 0
        if idle_workers:
            logger.debug(f"idle or new workers {idle_workers}")
            for worker in idle_workers:
                if self.minerals.has_unused_capacity:
                    logger.debug(f"adding {worker.tag} to minerals")
                    self.update_assigment(worker, JobType.MINERALS, None)
                    reassigned_count += 1
                    continue

                if self.vespene.has_unused_capacity:
                    logger.debug(f"adding {worker.tag} to gas")
                    self.update_assigment(worker, JobType.VESPENE, None)
                    reassigned_count += 1
                    continue

                if self.minerals.add_long_distance_minerals((idle_count - reassigned_count)) > 0:
                    logger.info(f"adding {worker.tag} to long-distance")
                    self.update_assigment(worker, JobType.MINERALS, None)
                else:
                    # nothing to do, just send them home
                    worker.move(self.bot.start_location)

        logger.debug(
            f"[==WORKERS==] minerals({len(self.assignments_by_job[JobType.MINERALS])}), "
            f"vespene({len(self.assignments_by_job[JobType.VESPENE])}), "
            f"builders({len(self.assignments_by_job[JobType.BUILD])}), "
            f"repairers({len(self.assignments_by_job[JobType.REPAIR])}), "
            f"idle({len(self.assignments_by_job[JobType.IDLE])}({len(self.bot.workers.idle)})), "
            f"total({len(self.assignments_by_worker.keys())}({len(self.bot.workers)}))"
        )
        self.stop_timer("my_workers.distribute_idle")

    async def redistribute_workers(self, needed_resources: Cost) -> int:
        await self.update_repairers()

        remaining_cooldown = 3 - (self.bot.time - self.last_worker_stop)
        if remaining_cooldown > 0:
            logger.debug(f"Distribute workers is on cooldown for {remaining_cooldown}")
            return -1

        max_workers_to_move = 10
        if needed_resources.vespene > -20:
            logger.debug("saturate vespene")
            return self.move_workers_to_vespene(max_workers_to_move)
        if needed_resources.minerals > 0:
            logger.debug("saturate minerals")
            return self.move_workers_to_minerals(max_workers_to_move)

        return 0

    async def update_repairers(self) -> None:
        injured_units = self.units_needing_repair()
        needed_repairers: int = 0
        missing_health = 0
        # limit to percentage of total workers
        max_repairers = min(self.max_repairers, math.floor(len(self.bot.workers) / 5))
        if injured_units:
            needed_repairers = 5  # early game, just assign a bunch so wall isn't broken by a rush
            if self.bot.time > 300:                
                for unit in injured_units:
                    missing_health += unit.health_max - unit.health
                    logger.debug(f"{unit} missing health {unit.health_max - unit.health}")
                needed_repairers = missing_health / self.health_per_repairer
                if needed_repairers > max_repairers:
                    needed_repairers = max_repairers
                elif needed_repairers < len(injured_units):
                    needed_repairers = max(needed_repairers, min(3, len(injured_units)))  # minimum of 3 repairers if there are multiple injured units

        current_repairers: Units = self.availiable_workers_on_job(JobType.REPAIR)
        repairer_shortage: int = round(needed_repairers) - len(current_repairers)
        logger.debug(f"missing health {missing_health} need repairers {needed_repairers} have {len(current_repairers)} shortage {repairer_shortage}")

        # remove excess repairers
        if repairer_shortage < 0:
            for i in range(-repairer_shortage):
                retiring_repairer = current_repairers.furthest_to(injured_units.random) if injured_units else current_repairers.random
                if self.vespene.has_unused_capacity:
                    self.update_assigment(retiring_repairer, JobType.VESPENE, None)
                elif self.minerals.has_unused_capacity:
                    self.update_assigment(retiring_repairer, JobType.MINERALS, None)
                else:
                    logger.debug(f"nowhere for {retiring_repairer} to retire to, staying repairer")
                    break
                current_repairers.remove(retiring_repairer)

        # tell existing to repair closest that isn't themself
        units_with_no_repairer: list[Unit] = []
        if self.bot.time < 300:
            units_with_no_repairer = [unit for unit in injured_units]
            if len(units_with_no_repairer) > 5:
                units_with_no_repairer = units_with_no_repairer[:5]  # spread out repairers to up to 5 units, mostly to keep initial wall repaired
        for repairer in current_repairers:
            self.update_assigment(repairer, JobType.REPAIR, self.get_repair_target(repairer, injured_units, units_with_no_repairer))
            assignment = self.assignments_by_worker[repairer.tag]
            await self.worker_micro.repair(repairer, assignment.target)

        # add more repairers
        if repairer_shortage > 0:
            candidates: Units = None
            candidates = Units([
                    worker for worker in self.bot.workers
                    if self.assignments_by_worker[worker.tag].job_type not in (JobType.BUILD, JobType.REPAIR)
                ], bot_object=self.bot)
            if len(injured_units) == 1:
                candidates = candidates.filter(lambda unit: unit.tag not in injured_units.tags)
            for i in range(repairer_shortage):
                if not candidates:
                    break
                unit_to_repair: Unit = None
                if units_with_no_repairer:
                    unit_to_repair = units_with_no_repairer[0]
                else:
                    unit_to_repair = injured_units.random
                repairer: Unit = candidates.closest_to(unit_to_repair)
                candidates.remove(repairer)

                if repairer:
                    self.update_assigment(repairer, JobType.REPAIR, self.get_repair_target(repairer, injured_units, units_with_no_repairer))
                    assignment = self.assignments_by_worker[repairer.tag]
                    await self.worker_micro.repair(repairer, assignment.target)
                else:
                    break

    def get_repair_target(self, repairer: Unit, injured_units: Units, units_needing_repair: list) -> Unit:
        other_units = injured_units.filter(lambda unit: unit.tag != repairer.tag)
        if other_units and len(units_needing_repair) > 0:
            other_units = other_units.filter(lambda unit: unit in units_needing_repair)
        new_target: Unit = None
        if other_units:
            new_target = other_units.closest_to(repairer)
            if new_target in units_needing_repair:
                units_needing_repair.remove(new_target)
        return new_target

    def units_needing_repair(self) -> Units:
        injured_mechanical_units = Units([], self.bot)
        if self.bot.time > 300:
            injured_mechanical_units = self.bot.units.filter(lambda unit: unit.is_mechanical
                                                            and unit.health < unit.health_max
                                                            and len(self.enemy.threats_to_repairer(unit)) == 0)
        logger.debug(f"injured mechanical units {injured_mechanical_units}")

        # can only repair fully built structures
        injured_structures = self.bot.structures.filter(lambda unit: unit.type_id != UnitTypeId.AUTOTURRET
                                                        and unit.build_progress == 1
                                                        and unit.health < unit.health_max
                                                        and ((self.bot.time < 300 and unit.type_id in (UnitTypeId.BUNKER, UnitTypeId.SUPPLYDEPOT))
                                                             or len(self.enemy.threats_to_repairer(unit, attack_range_buffer=-unit.radius)) == 0))
        logger.debug(f"injured structures {injured_structures}")
        return injured_mechanical_units + injured_structures

    def move_workers_to_minerals(self, number_to_move: int) -> int:
        return self.move_workers_between_resources(self.vespene, self.minerals, JobType.MINERALS, number_to_move)

    def move_workers_to_vespene(self, number_to_move: int) -> int:
        return self.move_workers_between_resources(self.minerals, self.vespene, JobType.VESPENE, number_to_move)

    def move_workers_between_resources(self, source: Resources, target: Resources, target_job: JobType, number_to_move: int) -> int:
        moved_count = 0
        resource_nodes = target.nodes_with_capacity()
        if not resource_nodes:
            return 0

        candidates: Units = None
        if target_job == JobType.VESPENE:
            candidates = self.availiable_workers_on_job(JobType.MINERALS)
        else:
            candidates = self.availiable_workers_on_job(JobType.VESPENE)

        while moved_count < number_to_move and candidates and resource_nodes:
            # prefer emptier nodes to limit congestion
            resource_nodes.sort(key=lambda r: r.needed_workers(), reverse=True)
            next_node: Unit = resource_nodes[0]
            worker = candidates.closest_to(next_node.node)
            candidates.remove(worker)
            self.update_assigment(worker, target_job, next_node.node)
            moved_count += 1
            resource_nodes = target.nodes_with_capacity()

        if moved_count:
            self.last_worker_stop = self.bot.time
        return moved_count

    def get_mineral_capacity(self) -> int:
        return self.minerals.get_worker_capacity()
