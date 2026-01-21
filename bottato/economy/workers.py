from collections import defaultdict
import math
from typing import Dict, List, Set
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.game_data import Cost
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.units import Units

from bottato.economy.minerals import Minerals
from bottato.economy.resources import ResourceNode, Resources
from bottato.economy.vespene import Vespene
from bottato.enemy import Enemy
from bottato.enums import UnitMicroType, WorkerJobType
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.unit_types import UnitTypes
from bottato.unit_reference_helper import UnitReferenceHelper


class WorkerAssignment():
    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.job_type: WorkerJobType = WorkerJobType.IDLE
        self.target: Unit | None = None
        self.unit_available: bool = True
        self.gather_position: Point2 | None = None
        self.dropoff_target: Unit | None = None
        self.dropoff_position: Point2 | None = None
        self.initial_gather_complete: bool = False
        self.is_returning = False
        self.on_attack_break = False
        self.attack_target_tag: int | None = None

    def __repr__(self) -> str:
        return f"WorkerAssignment({self.unit}({self.unit_available}), {self.job_type.name}, {self.target})"


class Workers(GeometryMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map) -> None:
        self.bot: BotAI = bot
        self.enemy = enemy
        self.map = map

        self.last_worker_stop = -1000
        self.assignments_by_worker: dict[int, WorkerAssignment] = {}
        self.assignments_by_job: dict[WorkerJobType, List[WorkerAssignment]] = {
            WorkerJobType.IDLE: [],
            WorkerJobType.MINERALS: [],
            WorkerJobType.VESPENE: [],
            WorkerJobType.BUILD: [],
            WorkerJobType.REPAIR: [],
            WorkerJobType.ATTACK: [],
            WorkerJobType.SCOUT: [],
        }
        self.minerals = Minerals(bot, self.map)
        self.vespene = Vespene(bot)
        self.max_workers = 75
        self.health_per_repairer = 50
        self.max_repairers = 10
        for worker in self.bot.workers:
            self.add_worker(worker)
        self.aged_mules: Units = Units([], bot)
        self.worker_micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.bot.workers.first)
        self.units_to_attack: Set[Unit] = set()
        self.workers_being_repaired: Set[int] = set()

    @timed
    def update_references(self, builder_tags: List[int]):
        self.minerals.update_references()
        self.vespene.update_references()
        self.workers_being_repaired.clear()

        self.assignments_by_job[WorkerJobType.IDLE].clear()
        self.assignments_by_job[WorkerJobType.MINERALS].clear()
        self.assignments_by_job[WorkerJobType.VESPENE].clear()
        self.assignments_by_job[WorkerJobType.BUILD].clear()
        self.assignments_by_job[WorkerJobType.REPAIR].clear()
        self.assignments_by_job[WorkerJobType.ATTACK].clear()
        self.assignments_by_job[WorkerJobType.SCOUT].clear()
        for assignment in self.assignments_by_worker.values():
            try:
                assignment.unit = UnitReferenceHelper.get_updated_unit_reference(assignment.unit)
                assignment.unit_available = True
            except UnitReferenceHelper.UnitNotFound:
                # unit is inside a structure
                assignment.unit_available = False

            try:
                assignment.target = UnitReferenceHelper.get_updated_unit_reference(assignment.target)
            except UnitReferenceHelper.UnitNotFound:
                assignment.target = None

            try:
                assignment.dropoff_target = UnitReferenceHelper.get_updated_unit_reference(assignment.dropoff_target)
            except UnitReferenceHelper.UnitNotFound:
                assignment.dropoff_target = None
                assignment.dropoff_position = None

            if assignment.unit_available:
                # keep workers in sync with build steps, minerals, and vespene
                if assignment.unit.tag in builder_tags:
                    assignment.job_type = WorkerJobType.BUILD
                elif assignment.job_type == WorkerJobType.BUILD:
                    assignment.job_type = WorkerJobType.IDLE
                elif assignment.job_type == WorkerJobType.MINERALS:
                    resource_node = self.minerals.get_node_by_worker_tag(assignment.unit.tag)
                    if resource_node:
                        assignment.target = resource_node.node
                    else:
                        assignment.target = None
                        assignment.unit(AbilityId.HALT)
                        assignment.job_type = WorkerJobType.IDLE
                elif assignment.job_type == WorkerJobType.VESPENE:
                    resource_node = self.vespene.get_node_by_worker_tag(assignment.unit.tag)
                    if resource_node:
                        assignment.target = resource_node.node
                    else:
                        assignment.target = None
                        assignment.unit(AbilityId.HALT)
                        assignment.job_type = WorkerJobType.IDLE

                if assignment.job_type != WorkerJobType.VESPENE:
                    self.vespene.remove_worker_by_tag(assignment.unit.tag)
                if assignment.job_type != WorkerJobType.MINERALS:
                    self.minerals.remove_worker_by_tag(assignment.unit.tag)

            self.assignments_by_job[assignment.job_type].append(assignment)
            self.bot.client.debug_text_3d(f"{assignment.job_type.name}\n{assignment.unit.tag}",
                                          assignment.unit.position3d + Point3((0, 0, 1)), size=8, color=(255, 255, 255))
        logger.debug(f"assignment summary {self.assignments_by_job}")

    def add_worker(self, worker: Unit) -> bool:
        if worker.tag not in self.assignments_by_worker:
            new_assignment = WorkerAssignment(worker)
            self.assignments_by_worker[worker.tag] = new_assignment
            self.assignments_by_job[WorkerJobType.IDLE].append(new_assignment)
            if worker.type_id == UnitTypeId.MULE:
                self.minerals.update_references()
                self.aged_mules.append(worker)
                minerals_with_capacity = self.minerals.nodes_with_mule_capacity()
                if not minerals_with_capacity:
                    self.update_assigment(worker, WorkerJobType.IDLE, None)
                else:
                    closest_minerals: Unit = self.closest_unit_to_unit(worker, minerals_with_capacity)
                    self.update_assigment(worker, WorkerJobType.MINERALS, closest_minerals)
                    self.minerals.add_mule(worker, closest_minerals)
                    logger.debug(f"added mule {worker.tag}({worker.position}) to minerals {closest_minerals}({closest_minerals.position})")
            return True
        return False

    @timed
    def drop_mules(self):
        # take off mules that are about to expire so they don't waste minerals
        for mule in self.aged_mules.copy():
            if mule.age > 58:
                try:
                    updated_mule = self.bot.units.by_tag(mule.tag)
                    if not updated_mule.is_carrying_resource:
                        updated_mule.move(self.bot.enemy_start_locations[0])
                        self.remove_mule(mule)
                        self.update_assigment(updated_mule, WorkerJobType.IDLE, None)
                except KeyError:
                    self.remove_mule(mule)

        reserve_for_scan = 0 if self.bot.units(UnitTypeId.RAVEN) else 60
        available_energy = 0
        for orbital in self.bot.townhalls(UnitTypeId.ORBITALCOMMAND):
            available_energy += orbital.energy
            if available_energy - reserve_for_scan < 50:
                continue
            mineral_fields: Units = self.minerals.nodes_with_mule_capacity().filter(lambda mf: self.closest_distance_squared(mf, self.bot.enemy_units) > 225)
            if mineral_fields:
                fullest_mineral_field: Unit = max(mineral_fields, key=lambda x: x.mineral_contents)
                nearest_townhall: Unit = self.bot.townhalls.closest_to(fullest_mineral_field)
                orbital(AbilityId.CALLDOWNMULE_CALLDOWNMULE,
                        target=fullest_mineral_field.position.towards(nearest_townhall),
                        queue=True)

    def remove_mule(self, mule: Unit):
        logger.debug(f"removing mule {mule}")
        self.minerals.remove_mule(mule)
        self.aged_mules.remove(mule)

    @timed_async
    async def speed_mine(self):
        assignment: WorkerAssignment
        for assignment in self.assignments_by_worker.values():
            if assignment.unit.tag in self.workers_being_repaired:
                repairers = self.availiable_workers_on_job(WorkerJobType.REPAIR)
                if repairers:
                    closest_repairer = self.closest_unit_to_unit(assignment.unit, repairers, self.enemy.predicted_position)
                    if closest_repairer.health_percentage < 1.0:
                        await self.worker_micro.repair(assignment.unit, closest_repairer)
                    else:
                        await self.worker_micro.move(assignment.unit, closest_repairer.position)
                    continue
            if assignment.on_attack_break \
                    or not assignment.unit_available \
                    or assignment.job_type not in [WorkerJobType.MINERALS, WorkerJobType.VESPENE] \
                    or assignment.unit.tag in self.workers_being_repaired \
                    or await self.worker_micro._retreat(assignment.unit, 0.7) != UnitMicroType.NONE:
                continue
            
            if not self.bot.townhalls.ready:
                LogHelper.add_log(
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

    def sharpy_speed_mine(self, assignment: WorkerAssignment) -> None:
        worker = assignment.unit
        townhall = self.bot.townhalls.closest_to(worker)

        if worker.is_returning and len(worker.orders) == 1:
            return_target: Point2 = townhall.position
            return_target = return_target.towards(worker, townhall.radius + worker.radius)
            if 0.75 < worker.distance_to(return_target) < 2:
                worker.move(return_target)
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
                target: Point2 | None = assignment.gather_position
                if target:
                    worker_distance = worker.distance_to(target)
                    if 0.75 < worker_distance < 2:
                        worker.move(target)
                        worker(AbilityId.SMART, mf, True)
                    elif worker_distance <= 0.75:
                        first_order = worker.orders[0]
                        if first_order.ability.id != AbilityId.HARVEST_GATHER \
                                or first_order.target != mf.tag:
                            worker(AbilityId.SMART, mf)

    TOWNHALL_RADIUS: float = 2.75
    DISTANCE_TO_TOWNHALL_FACTOR: float = 1.08
    @timed
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
                    if closest_townhall.distance_to_squared(worker) < 225:
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

        elif not worker.is_returning and len_orders < 2 and assignment.target and assignment.gather_position:
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
            elif assignment.target:
                worker.gather(assignment.target)
            return True

        return False

    @timed
    def bottato_speed_mine(self, assignment: WorkerAssignment) -> None:
        worker = assignment.unit
        if worker.is_carrying_resource:
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
        elif assignment.target:
            if assignment.initial_gather_complete:
                if assignment.gather_position is None:
                    assignment.gather_position = self.minerals.nodes_by_tag[assignment.target.tag].mining_position
                if assignment.gather_position:
                    if assignment.is_returning:
                        assignment.is_returning = False
                        worker.move(assignment.gather_position)
                    elif len(worker.orders) == 1 and assignment.target:
                        self.speed_smart(worker, assignment.target, assignment.gather_position)
            else:
                # first time gathering, just gather
                worker.gather(assignment.target)

    @timed
    def speed_smart(self, worker: Unit, target: Unit | None, position: Point2 | None = None) -> None:
        if position is None or target is None:
            return
        remaining_distance = worker.distance_to_squared(position)
        if 0.5625 < remaining_distance < 3.0625:
            worker.move(position)
            worker(AbilityId.SMART, target, True)
        elif remaining_distance <= 0.5625:
            first_order = worker.orders[0]
            if first_order.ability.id != AbilityId.HARVEST_GATHER or first_order.target != target.tag:
                worker(AbilityId.SMART, target)

    @timed_async
    async def attack_nearby_enemies(self) -> None:
        defender_tags = set()
        if self.bot.townhalls and self.bot.time < 200:
            available_workers = self.bot.workers.filter(lambda u: self.assignments_by_worker[u.tag].job_type in {WorkerJobType.MINERALS, WorkerJobType.VESPENE})
            healthy_workers = available_workers.filter(lambda u: u.health_percentage > 0.5)
            unhealthy_workers = available_workers.filter(lambda u: u.health_percentage <= 0.5)

            for worker in self.bot.workers:
                assignment = self.assignments_by_worker[worker.tag]
                targetable_enemies = self.bot.enemy_units.filter(lambda u: not u.is_flying and UnitTypes.can_be_attacked(u, self.bot, self.enemy.get_enemies()))
                nearby_enemies = targetable_enemies.closer_than(4, worker)
                if nearby_enemies:
                    if worker.health_percentage < 0.6 and assignment.job_type == WorkerJobType.BUILD:
                        # stop building if getting attacked
                        worker(AbilityId.HALT)

                    if len(nearby_enemies) >= len(available_workers):
                        continue
                    for nearby_enemy in nearby_enemies:
                        predicted_position = self.enemy.get_predicted_position(nearby_enemy, 2.0)
                        defender_tags.update(await self.send_defenders(nearby_enemy, healthy_workers, unhealthy_workers, 2))

            for townhall in self.bot.townhalls:
                nearby_enemy_structures = self.bot.enemy_structures.closer_than(23, townhall).filter(lambda u: not u.is_flying)
                if nearby_enemy_structures:
                    nearby_enemy_structures.sort(key=lambda a: (a.type_id != UnitTypeId.PHOTONCANNON) * 1000000 + a.distance_to_squared(townhall))
                nearby_enemy_range = 25 if nearby_enemy_structures else 12
                nearby_enemies = self.bot.enemy_units.closer_than(nearby_enemy_range, townhall).filter(lambda u: not u.is_flying and UnitTypes.can_be_attacked(u, self.bot, self.enemy.get_enemies()))
                for enemy in self.units_to_attack:
                    predicted_position = self.enemy.get_predicted_position(enemy, 0.0)
                    if predicted_position._distance_squared(townhall.position) < 625:
                        nearby_enemies.append(enemy)
                if nearby_enemies or nearby_enemy_structures:
                    logger.debug(f"units_to_attack: {self.units_to_attack}")
                    logger.debug(f"nearby enemy structures: {nearby_enemy_structures}, nearby enemies: {nearby_enemies}")

                if len(nearby_enemies) >= len(available_workers):
                    # don't suicide workers if outnumbered
                    continue
                # assign closest 3 workers to attack each enemy
                workers_per_enemy_unit = 2 if nearby_enemy_structures or self.bot.enemy_race != Race.Protoss else 3
                for nearby_enemy in nearby_enemies + nearby_enemy_structures:
                    predicted_position = self.enemy.get_predicted_position(nearby_enemy, 2.0)
                    number_of_attackers = 4 if nearby_enemy.is_structure else workers_per_enemy_unit
                    townhall_defenders = await self.send_defenders(nearby_enemy, healthy_workers, unhealthy_workers, number_of_attackers)
                    if not townhall_defenders:
                        logger.debug(f"no attackers available for enemy {nearby_enemy}")
                        break
                    defender_tags.update(townhall_defenders)

        # put any leftover workers back to work
        for worker in self.bot.workers:
            assignment = self.assignments_by_worker[worker.tag]
            if assignment.on_attack_break and worker.tag not in defender_tags:
                assignment.on_attack_break = False
                if assignment.target:
                    if assignment.unit.is_carrying_resource and self.bot.townhalls:
                        assignment.unit.smart(self.bot.townhalls.closest_to(assignment.unit))
                    else:
                        assignment.unit.smart(assignment.target)

    async def send_defenders(self, nearby_enemy: Unit, healthy_workers: Units, unhealthy_workers: Units, number_of_attackers: int) -> set[int]:
        enemy_position = nearby_enemy if nearby_enemy.age == 0 else self.enemy.get_predicted_position(nearby_enemy, 0.0)
        if len(healthy_workers) >= number_of_attackers:
            defenders = healthy_workers.closest_n_units(enemy_position, number_of_attackers)
            for defender in defenders:
                healthy_workers.remove(defender)
        else:
            defenders = Units([worker for worker in healthy_workers], self.bot)
            healthy_workers.clear()
            if unhealthy_workers:
                remainder = number_of_attackers - len(defenders)

                if len(unhealthy_workers) >= remainder:
                    unhealthy_defenders = unhealthy_workers.closest_n_units(enemy_position, remainder)
                    for defender in unhealthy_defenders:
                        unhealthy_workers.remove(defender)
                    defenders.extend(unhealthy_defenders)
                else:
                    defenders.extend([worker for worker in unhealthy_workers])
                    unhealthy_workers.clear()

        micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.bot.workers.first)
        for defender in defenders:
            if defender.distance_to_squared(enemy_position) > 625 or abs(self.bot.get_terrain_height(defender.position) - self.bot.get_terrain_height(enemy_position)) > 5:
                # don't pull workers from far away or go down a ramp
                logger.debug(f"worker {defender} too far from enemy {nearby_enemy}")
                continue
            if nearby_enemy.is_structure:
                defender.attack(nearby_enemy)
            elif nearby_enemy.is_facing(defender, angle_error=0.15):
                # in front of enemy, turn to attack it
                await micro.move(defender, nearby_enemy.position)
            else:
                # try to head off units instead of trailing after them
                await micro.move(defender, enemy_position.position)
            self.assignments_by_worker[defender.tag].on_attack_break = True

        return defenders.tags

    def attack_enemy(self, enemy: Unit):
        for existing_enemy in self.units_to_attack:
            if existing_enemy.tag == enemy.tag:
                self.units_to_attack.remove(existing_enemy)
                logger.debug(f"updated enemy to attack {enemy}")
                break
        LogHelper.add_log(f"added enemy to attack {enemy}")
        self.units_to_attack.add(enemy)

    def update_assigment(self, worker: Unit, job_type: WorkerJobType, target: Unit | None):
        self.update_job(worker, job_type)
        if not self.update_target(worker, target):
            self.update_job(worker, WorkerJobType.REPAIR)
            self.update_target(worker)

    def update_job(self, worker: Unit, new_job: WorkerJobType):
        if worker.tag not in self.assignments_by_worker:
            return
        assignment = self.assignments_by_worker[worker.tag]
        if assignment.job_type == new_job:
            return

        if assignment.job_type == WorkerJobType.MINERALS:
            self.minerals.remove_worker(worker)
        elif assignment.job_type == WorkerJobType.VESPENE:
            self.vespene.remove_worker(worker)

        self.assignments_by_job[assignment.job_type].remove(assignment)
        assignment.job_type = new_job
        self.assignments_by_job[new_job].append(assignment)

    def update_target(self, worker: Unit, new_target: Unit | None = None) -> bool:
        if worker.tag not in self.assignments_by_worker:
            return True
        assignment = self.assignments_by_worker[worker.tag]
        logger.debug(f"worker {worker} changing from {assignment.target} to {new_target}")
        if new_target:
            if assignment.job_type == WorkerJobType.REPAIR:
                pass
            elif assignment.job_type == WorkerJobType.VESPENE:
                if self.vespene.add_worker_to_node(worker, new_target):
                    assignment.gather_position = new_target.position
                    if worker.is_carrying_resource and self.bot.townhalls:
                        worker.smart(self.bot.townhalls.closest_to(worker))
                    else:
                        worker.smart(new_target)
                else:
                    return False
            elif assignment.job_type == WorkerJobType.MINERALS:
                if self.minerals.add_worker_to_node(worker, new_target):
                    assignment.gather_position = self.minerals.nodes_by_tag[new_target.tag].mining_position
                    assignment.dropoff_target = None
                    assignment.dropoff_position = None
                    if worker.is_carrying_resource and self.bot.townhalls:
                        worker.smart(self.bot.townhalls.closest_to(worker))
                    else:
                        worker.gather(new_target)
                else:
                    return False
            else:
                worker.smart(new_target)
        else:
            if assignment.job_type == WorkerJobType.REPAIR:
                pass
            elif assignment.job_type == WorkerJobType.MINERALS:
                new_target = self.minerals.add_worker(worker)
                if new_target is None:
                    # No capacity available, keep worker idle
                    logger.warning(f"No mineral capacity for worker {worker}, keeping idle")
                    return False
                assignment.gather_position = self.minerals.nodes_by_tag[new_target.tag].mining_position
                assignment.dropoff_target = None
                assignment.dropoff_position = None
                if worker.is_carrying_resource and self.bot.townhalls:
                    worker.smart(self.bot.townhalls.closest_to(worker))
                else:
                    worker.smart(new_target)
            elif assignment.job_type == WorkerJobType.VESPENE:
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

    def record_death(self, unit_tag):
        if unit_tag in self.assignments_by_worker:
            del self.assignments_by_worker[unit_tag]
            # assign_by_job should be cleaned up by update_references refresh
            self.minerals.remove_worker_by_tag(unit_tag)
            self.vespene.remove_worker_by_tag(unit_tag)
        else:
            self.minerals.record_non_worker_death(unit_tag)
        for existing_enemy in self.units_to_attack:
            if existing_enemy.tag == unit_tag:
                self.units_to_attack.remove(existing_enemy)
                break

    def get_builder(self, building_position: Point2):
        builder = None
        candidates: Units = (
            self.availiable_workers_on_job(WorkerJobType.IDLE)
            + self.availiable_workers_on_job(WorkerJobType.VESPENE)
            + self.availiable_workers_on_job(WorkerJobType.MINERALS)
            # + self.availiable_workers_on_job(JobType.REPAIR)
        )
        if not candidates:
            logger.debug("FAILED TO GET BUILDER")
        else:
            builder = candidates.closest_to(building_position)
            if builder is not None:
                logger.debug(f"found builder {builder}")
                self.update_assigment(builder, WorkerJobType.BUILD, None)

        return builder

    def get_scout(self, position: Point2) -> Unit | None:
        scout: Unit | None = None
        candidates: Units = (
            self.availiable_workers_on_job(WorkerJobType.IDLE)
            or self.availiable_workers_on_job(WorkerJobType.VESPENE)
            or self.availiable_workers_on_job(WorkerJobType.MINERALS)
            or self.availiable_workers_on_job(WorkerJobType.REPAIR)
        )
        if not candidates:
            logger.debug("FAILED TO GET SCOUT")
        else:
            healthy_candidates = candidates.filter(lambda u: u.health_percentage == 1.0)
            scout = healthy_candidates.closest_to(position) if healthy_candidates else candidates.closest_to(position)
            if scout is not None:
                logger.debug(f"found scout {scout}")
                self.update_assigment(scout, WorkerJobType.SCOUT, None)

        return scout

    def availiable_workers_on_job(self, job_type: WorkerJobType) -> Units:
        return Units([
            assignment.unit for assignment in self.assignments_by_job[job_type]
            if assignment.unit_available
                and assignment.unit.type_id != UnitTypeId.MULE
                and not (assignment.job_type in (WorkerJobType.MINERALS, WorkerJobType.VESPENE) and assignment.unit.is_carrying_resource)
                and not assignment.on_attack_break
        ],
            bot_object=self.bot)

    def set_as_idle(self, worker: Unit):
        if worker.tag in self.assignments_by_worker:
            self.update_assigment(worker, WorkerJobType.IDLE, None)

    builder_idle_time: dict[int, float] = {}
    @timed
    def distribute_idle(self):
        if self.bot.workers.idle:
            logger.debug(f"idle workers {self.bot.workers.idle}")
        tags_to_remove = [tag for tag in self.builder_idle_time if tag not in self.bot.workers.idle.tags]
        for tag in tags_to_remove:
            del self.builder_idle_time[tag]
        for worker in self.bot.workers.idle:
            assigment: WorkerAssignment = self.assignments_by_worker[worker.tag]
            if assigment.unit.type_id == UnitTypeId.MULE:
                continue
            elif assigment.job_type == WorkerJobType.BUILD and (not assigment.target or not assigment.target.is_ready):
                if worker.tag not in self.builder_idle_time:
                    self.builder_idle_time[worker.tag] = self.bot.time
                    continue
                elif self.bot.time - self.builder_idle_time[worker.tag] < 5:
                    # wait up to 5 seconds before determining worker is idle
                    continue
                else:
                    del self.builder_idle_time[worker.tag]
            elif assigment.job_type == WorkerJobType.SCOUT:
                continue
            elif assigment.job_type == WorkerJobType.IDLE:
                continue
            self.set_as_idle(worker)
        for worker in self.minerals.get_workers_from_depleted() + self.vespene.get_workers_from_depleted():
            self.set_as_idle(worker)
        for worker in self.minerals.get_workers_from_overcapacity():
            self.set_as_idle(worker)

        idle_workers: Units = self.availiable_workers_on_job(WorkerJobType.IDLE)
        idle_count = len(idle_workers)
        reassigned_count = 0
        if idle_workers:
            logger.debug(f"idle or new workers {idle_workers}")
            for worker in idle_workers:
                if self.minerals.has_unused_capacity:
                    logger.debug(f"adding {worker.tag} to minerals")
                    self.update_assigment(worker, WorkerJobType.MINERALS, None)
                    reassigned_count += 1
                    continue

                if self.vespene.has_unused_capacity:
                    logger.debug(f"adding {worker.tag} to gas")
                    self.update_assigment(worker, WorkerJobType.VESPENE, None)
                    reassigned_count += 1
                    continue

                if self.minerals.add_long_distance_minerals((idle_count - reassigned_count)) > 0:
                    LogHelper.add_log(f"adding {worker.tag} to long-distance")
                    self.update_assigment(worker, WorkerJobType.MINERALS, None)
                else:
                    # nothing to do, just send them home
                    worker.move(self.bot.start_location)

        logger.debug(
            f"[==WORKERS==] minerals({len(self.assignments_by_job[WorkerJobType.MINERALS])}), "
            f"vespene({len(self.assignments_by_job[WorkerJobType.VESPENE])}), "
            f"builders({len(self.assignments_by_job[WorkerJobType.BUILD])}), "
            f"repairers({len(self.assignments_by_job[WorkerJobType.REPAIR])}), "
            f"idle({len(self.assignments_by_job[WorkerJobType.IDLE])}({len(self.bot.workers.idle)})), "
            f"total({len(self.assignments_by_worker.keys())}({len(self.bot.workers)}))"
        )

    @timed_async
    async def redistribute_workers(self, needed_resources: Cost) -> int:
        await self.update_repairers()
        self.distribute_idle()

        remaining_cooldown = 3 - (self.bot.time - self.last_worker_stop)
        if remaining_cooldown > 0:
            logger.debug(f"Distribute workers is on cooldown for {remaining_cooldown}")
            return -1

        max_workers_to_move = 10
        if needed_resources.vespene < 20:
            logger.debug("saturate vespene")
            return self.move_workers_to_vespene(max_workers_to_move)
        if needed_resources.minerals < 0:
            logger.debug("saturate minerals")
            return self.move_workers_to_minerals(max_workers_to_move)

        return 0

    @timed_async
    async def update_repairers(self) -> None:
        injured_units = self.units_needing_repair()
        needed_repairers: int = 0
        assigned_repairers: Units = Units([], bot_object=self.bot)
        units_with_no_repairer: List[Unit] = []
        if injured_units:
            missing_health = 0
            # limit to percentage of total workers
            max_repairers = min(self.max_repairers, math.floor(len(self.bot.workers) / 5))
            candidates: Units = Units([
                            worker for worker in self.bot.workers
                            if self.assignments_by_worker[worker.tag].job_type != WorkerJobType.BUILD
                        ], bot_object=self.bot)

            for injured_unit in injured_units:
                if injured_unit.type_id == UnitTypeId.BUNKER:
                    assigned_repairers.extend(await self.assign_repairers_to_structure(injured_unit, 5, candidates))
                elif injured_unit.type_id == UnitTypeId.MISSILETURRET:
                    flying_enemies = self.bot.enemy_units.filter(lambda u: u.is_flying)
                    if self.closest_distance_squared(injured_unit, flying_enemies) > 121:
                        # don't waste repairers on missile turrets that don't have targets
                        continue
                    assigned_repairers.extend(await self.assign_repairers_to_structure(injured_unit, 3, candidates))
                elif injured_unit.type_id == UnitTypeId.PLANETARYFORTRESS:
                    if injured_unit.health_max - injured_unit.health < 50:
                        assigned_repairers.extend(await self.assign_repairers_to_structure(injured_unit, 2, candidates))
                    else:
                        assigned_repairers.extend(await self.assign_repairers_to_structure(injured_unit, 8, candidates))
                elif injured_unit.type_id == UnitTypeId.SIEGETANKSIEGED and self.bot.townhalls and self.bot.townhalls.closest_distance_to(injured_unit) < 20:
                    assigned_repairers.extend(await self.assign_repairers_to_structure(injured_unit, 3, candidates))
                else:
                    missing_health += injured_unit.health_max - injured_unit.health
                    if self.bot.time < 300:
                        units_with_no_repairer.append(injured_unit)

            if missing_health > 0 and self.bot.time < 180:
                # early game, just assign a bunch so wall isn't broken by a rush
                needed_repairers = max(needed_repairers, 5)
            else:
                needed_repairers = math.ceil(missing_health / self.health_per_repairer)
                if needed_repairers > max_repairers:
                    needed_repairers = max_repairers
                else:
                    # minimum 1 repairer per injured, up to 3. mostly for repairing initial wall
                    needed_repairers = max(needed_repairers, min(3, len(injured_units)))
            
        current_repairers: Units = self.availiable_workers_on_job(WorkerJobType.REPAIR).filter(
            lambda u: u.tag not in assigned_repairers.tags)
        current_repair_targets = {}
        for worker in current_repairers:
            if worker.is_repairing and not worker.is_moving:
                current_repair_targets[worker.orders[0].target] = worker.tag
            elif worker.health_percentage < 0.5:
                self.set_as_idle(worker)
                current_repairers.remove(worker)

        repairer_shortage: int = needed_repairers - len(current_repairers)

        # remove excess repairers
        if repairer_shortage < 0:
            # don't retire mid-repair
            inactive_repairers: Units = current_repairers.filter(lambda unit: not unit.is_repairing)
            inactive_repairers.sort(key=lambda r: r.health)
            for i in range(-repairer_shortage):
                if not inactive_repairers:
                    break
                lowest_health_repairer = inactive_repairers.first
                retiring_repairer: Unit
                if lowest_health_repairer.health_percentage < 1.0 or len(injured_units) == 0:
                    retiring_repairer = lowest_health_repairer
                else:
                    retiring_repairer = inactive_repairers.furthest_to(injured_units.random)
                if self.vespene.has_unused_capacity:
                    self.update_assigment(retiring_repairer, WorkerJobType.VESPENE, None)
                elif self.minerals.has_unused_capacity:
                    self.update_assigment(retiring_repairer, WorkerJobType.MINERALS, None)
                else:
                    self.set_as_idle(retiring_repairer)
                inactive_repairers.remove(retiring_repairer)
                current_repairers.remove(retiring_repairer)

        if len(units_with_no_repairer) > 5:
            units_with_no_repairer = units_with_no_repairer[:5]  # spread out repairers to up to 5 units, mostly to keep initial wall repaired

        for repairer in current_repairers:
            if repairer.is_constructing_scv:
                # mixed up job somehow, stop constructing so it can go repair, probably an idle scv is trying to do the build
                repairer(AbilityId.HALT)
                continue
            repair_target = self.get_repair_target(repairer, injured_units, units_with_no_repairer)
            self.update_assigment(repairer, WorkerJobType.REPAIR, repair_target)
            if repair_target:
                await self.worker_micro.repair(repairer, repair_target)
                if not repair_target.is_structure:
                    current_repairer_tag = current_repair_targets.get(repair_target.tag, repairer.tag)
                    if current_repairer_tag == repairer.tag:
                        if repair_target.type_id == UnitTypeId.SCV:
                            self.workers_being_repaired.add(repair_target.tag)

        # add more repairers
        if repairer_shortage > 0:
            candidates: Units = Units([
                    worker for worker in self.bot.workers
                    if self.assignments_by_worker[worker.tag].job_type not in (WorkerJobType.BUILD, WorkerJobType.REPAIR)
                    and worker.health_percentage > 0.5
                ], bot_object=self.bot)
            if len(injured_units) == 1:
                candidates = candidates.filter(lambda unit: unit.tag not in injured_units.tags)
            for i in range(repairer_shortage):
                if not candidates:
                    break
                unit_to_repair: Unit | None = None
                if units_with_no_repairer:
                    unit_to_repair = units_with_no_repairer[0]
                else:
                    unit_to_repair = injured_units.random
                repairer: Unit = candidates.closest_to(unit_to_repair)
                if not repairer:
                    break
                if not unit_to_repair.is_structure:
                    repairer_distance = repairer.distance_to(unit_to_repair)
                    if unit_to_repair.type_id == UnitTypeId.SCV and repairer_distance > 10 or repairer_distance > 60 and self.bot.time < 600:
                        # don't send repairer too far to repair
                        continue

                candidates.remove(repairer)
                repair_target = self.get_repair_target(repairer, injured_units, units_with_no_repairer)
                self.update_assigment(repairer, WorkerJobType.REPAIR, repair_target)
                if repair_target:
                    await self.worker_micro.repair(repairer, repair_target)
                    if not repair_target.is_structure:
                        current_repairer_tag = current_repair_targets.get(repair_target.tag, repairer.tag)
                        if current_repairer_tag == repairer.tag:
                            if repair_target.type_id == UnitTypeId.SCV:
                                self.workers_being_repaired.add(repair_target.tag)
    
    async def assign_repairers_to_structure(self, injured_structure: Unit, number_of_repairers: int, candidates: Units) -> Units:
        repairers: Units = candidates.closest_n_units(injured_structure, number_of_repairers)
        assigned_count = 0
        for repairer in repairers:
            candidates.remove(repairer)
            self.update_assigment(repairer, WorkerJobType.REPAIR, injured_structure)
            if await self.worker_micro.repair(repairer, injured_structure) == UnitMicroType.REPAIR:
                assigned_count += 1
        LogHelper.add_log(f"assigned {assigned_count} of {repairers} to repair {injured_structure}")
        return repairers

    def get_repair_target(self, repairer: Unit, injured_units: Units, units_needing_repair: list) -> Unit | None:
        other_units = injured_units.filter(lambda unit: unit.tag != repairer.tag)
        if other_units and len(units_needing_repair) > 0:
            other_units = other_units.filter(lambda unit: unit in units_needing_repair)
        new_target: Unit | None = None
        if other_units:
            new_target = other_units.closest_to(repairer)
            if new_target in units_needing_repair:
                units_needing_repair.remove(new_target)
        return new_target

    ramp_wall_structers: Set[UnitTypeId] = set([
        UnitTypeId.BARRACKS,
        UnitTypeId.BARRACKSREACTOR,
        UnitTypeId.SUPPLYDEPOT,
    ])
    defensive_structures: Set[UnitTypeId] = set([
        UnitTypeId.BUNKER,
        UnitTypeId.MISSILETURRET,
        UnitTypeId.PLANETARYFORTRESS,
    ])
    def units_needing_repair(self) -> Units:
        injured_mechanical_units = Units([], self.bot)
        # repair_scvs = self.bot.time > 240
        injured_mechanical_units = self.bot.units.filter(lambda unit: unit.is_mechanical
                                                         and unit.type_id != UnitTypeId.MULE
                                                         and unit.health < unit.health_max
                                                        #  and (repair_scvs or unit.type_id != UnitTypeId.SCV)
                                                         and (
                                                             unit.type_id == UnitTypeId.SIEGETANKSIEGED and self.bot.townhalls and self.bot.townhalls.closest_distance_to(unit) < 20
                                                            or len(self.enemy.threats_to_repairer(unit, attack_range_buffer=0)) == 0))
        logger.debug(f"injured mechanical units {injured_mechanical_units}")

        # can only repair fully built structures
        injured_structures = self.bot.structures.filter(lambda unit: unit.type_id != UnitTypeId.AUTOTURRET
                                                        and unit.build_progress == 1
                                                        and unit.health < unit.health_max
                                                        and ((self.bot.time < 300 and unit.type_id in self.ramp_wall_structers)
                                                             or unit.type_id in self.defensive_structures
                                                             or len(self.enemy.threats_to_repairer(unit, attack_range_buffer=-unit.radius)) == 0))
        logger.debug(f"injured structures {injured_structures}")
        return injured_mechanical_units + injured_structures

    def move_workers_to_minerals(self, number_to_move: int) -> int:
        return self.move_workers_between_resources(self.vespene, self.minerals, WorkerJobType.MINERALS, number_to_move)

    def move_workers_to_vespene(self, number_to_move: int) -> int:
        return self.move_workers_between_resources(self.minerals, self.vespene, WorkerJobType.VESPENE, number_to_move)

    def move_workers_between_resources(self, source: Resources, target: Resources, target_job: WorkerJobType, number_to_move: int) -> int:
        moved_count = 0
        resource_nodes = target.nodes_with_capacity()
        if not resource_nodes:
            return 0

        candidates: Units | None = None
        if target_job == WorkerJobType.VESPENE:
            candidates = self.availiable_workers_on_job(WorkerJobType.MINERALS)
        else:
            candidates = self.availiable_workers_on_job(WorkerJobType.VESPENE)

        while moved_count < number_to_move and candidates and resource_nodes:
            # prefer emptier nodes to limit congestion
            resource_nodes.sort(key=lambda r: r.needed_workers(), reverse=True)
            next_node: ResourceNode = resource_nodes[0]
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
