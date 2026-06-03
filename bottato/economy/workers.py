
import math
from collections import defaultdict
from loguru import logger
from typing import Dict, List, Set

from cython_extensions import cy_distance_to_squared, cy_towards
from cython_extensions.combat_utils import cy_is_facing
from cython_extensions.general_utils import cy_in_pathing_grid_burny
from cython_extensions.geometry import cy_distance_to
from cython_extensions.units_utils import cy_closer_than, cy_closest_to
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
from bottato.enums import BuildType, Tactic, UnitMicroType, WorkerJobType
from bottato.log_helper import LogHelper
from bottato.magic_numbers import MagicNumbers as MN
from bottato.map_specifics import MapSpecifics
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.tactics import Tactics
from bottato.unit_reference_helper import UnitReferenceHelper
from bottato.unit_types import UnitTypes


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

    def __repr__(self) -> str:
        return f"WorkerAssignment({self.unit}({self.unit_available}), {self.job_type.name}, {self.target})"


class Workers(GeometryMixin):
    def __init__(self, bot: BotAI, tactics: Tactics) -> None:
        self.bot: BotAI = bot
        self.tactics: Tactics = tactics
        self.enemy = tactics.enemy
        self.map = tactics.map

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
                assignment.unit = UnitReferenceHelper.get_updated_unit(assignment.unit)
                assignment.unit_available = True
            except UnitReferenceHelper.UnitNotFound:
                # unit is inside a structure
                assignment.unit_available = False

            try:
                assignment.target = UnitReferenceHelper.get_updated_unit(assignment.target)
            except UnitReferenceHelper.UnitNotFound:
                assignment.target = None

            try:
                assignment.dropoff_target = UnitReferenceHelper.get_updated_unit(assignment.dropoff_target)
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

                # if assignment.job_type != WorkerJobType.VESPENE:
                #     self.vespene.remove_worker_by_tag(assignment.unit.tag)
                # if assignment.job_type != WorkerJobType.MINERALS:
                #     self.minerals.remove_worker_by_tag(assignment.unit.tag)

            self.assignments_by_job[assignment.job_type].append(assignment)
            self.bot.client.debug_text_3d(f"{assignment.job_type.name}\n{assignment.unit.tag}",
                                          assignment.unit.position3d + Point3((0, 0, 1)), size=8, color=(255, 255, 255))

        mineral_worker_tags = {a.unit.tag for a in self.assignments_by_job[WorkerJobType.MINERALS]}
        gas_worker_tags = {a.unit.tag for a in self.assignments_by_job[WorkerJobType.VESPENE]}
        self.minerals.remove_unassigned_workers(mineral_worker_tags)
        self.vespene.remove_unassigned_workers(gas_worker_tags)
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
            if mule.age > MN.MULE_AGE_LIMIT:
                try:
                    updated_mule = self.bot.units.by_tag(mule.tag)
                    if not updated_mule.is_carrying_resource:
                        updated_mule.move(self.bot.enemy_start_locations[0])
                        self.remove_mule(mule)
                        self.update_assigment(updated_mule, WorkerJobType.IDLE, None)
                except KeyError:
                    self.remove_mule(mule)

        reserve_for_scan = 0 if self.bot.units(UnitTypeId.RAVEN) else MN.SCAN_RESERVE_ENERGY
        available_energy = 0
        for orbital in self.bot.townhalls(UnitTypeId.ORBITALCOMMAND):
            available_energy += orbital.energy
            if available_energy - reserve_for_scan < MN.MULE_ENERGY_COST:
                continue
            mineral_fields: Units = self.minerals.nodes_with_mule_capacity().filter(
                lambda mf: self.closest_distance_squared(mf, self.bot.enemy_units) > MN.MULE_MIN_ENEMY_DISTANCE_SQ)
            if mineral_fields:
                fullest_mineral_field: Unit = max(mineral_fields, key=lambda x: x.mineral_contents)
                nearest_townhall: Unit = cy_closest_to(fullest_mineral_field.position, self.bot.townhalls)
                orbital(AbilityId.CALLDOWNMULE_CALLDOWNMULE,
                        target=Point2(cy_towards(fullest_mineral_field.position, nearest_townhall.position, 1)),
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
                    closest_repairer = self.closest_unit_to_unit(assignment.unit, repairers, self.enemy.predicted_positions)
                    if closest_repairer.health_percentage < 1.0:
                        await self.worker_micro.repair(assignment.unit, closest_repairer)
                    else:
                        await self.worker_micro.move(assignment.unit, closest_repairer.position)
                    continue
            if assignment.on_attack_break \
                    or not assignment.unit_available \
                    or assignment.job_type not in [WorkerJobType.MINERALS, WorkerJobType.VESPENE] \
                    or await self.worker_micro._retreat(assignment.unit,
                                                        MN.WORKER_SPEED_MINE_RETREAT_HEALTH_PERCENT_THRESHOLD) != UnitMicroType.NONE:
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
        townhall = cy_closest_to(worker.position, self.bot.townhalls)

        if worker.is_returning and len(worker.orders) == 1:
            return_target: Point2 = townhall.position
            return_target = Point2(cy_towards(return_target, worker.position, townhall.radius + worker.radius))
            if 0.75 < cy_distance_to(worker.position, return_target) < 2:
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
                    worker_distance = cy_distance_to(worker.position, target)
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
                cy_towards(target_pos, worker.position, self.TOWNHALL_RADIUS * self.DISTANCE_TO_TOWNHALL_FACTOR)
            )

            if 0.5625 < cy_distance_to_squared(worker.position, target_pos) < 4.0:
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
            worker_distance: float = cy_distance_to_squared(worker.position, assignment.gather_position) if assignment.gather_position else math.inf
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
                        assignment.dropoff_target = cy_closest_to(worker.position, dropoff_candidates)
                        min_distance = assignment.dropoff_target.radius + worker.radius
                        towards_distance = min(min_distance, cy_distance_to(worker.position, assignment.dropoff_target.position))
                        position = Point2(cy_towards(assignment.dropoff_target.position, worker.position, towards_distance))
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
        remaining_distance = cy_distance_to_squared(worker.position, position)
        if 0.5625 < remaining_distance < 3.0625:
            worker.move(position)
            worker(AbilityId.SMART, target, True)
        elif remaining_distance <= 0.5625:
            first_order = worker.orders[0]
            if first_order.ability.id != AbilityId.HARVEST_GATHER or first_order.target != target.tag:
                worker(AbilityId.SMART, target)

    min_workers_to_keep_on_minerals = MN.WORKER_ATTACK_PULL_RESERVE_MINERS

    use_cool_defense: bool = False
    @timed_async
    async def attack_nearby_enemies(self, enemy_builds_detected: Dict[BuildType, float]) -> None:
        """Two-phase worker defense: select fighters, then control them.

        Phase 1 — Selection: find enemies near workers/bases, pick closest
        unassigned workers as responders (same approach as before).

        Phase 2 — Control (priority order per fighter):
          1. Retreat via mineral walk if low health.
          2. Attack enemy if in range (or nearly) and healthy enough.
          3. Repair a nearby friendly worker that needs it.
          4. Mineral-walk toward the enemy if obstructed, else move toward them.
        """
        defender_tags: set[int] = set()

        if not (self.bot.townhalls and self.bot.workers):
            self._release_non_defenders(defender_tags)
            return

        # After early game, workers only fight back against very close enemies
        if self.bot.time >= MN.WORKER_ATTACK_PULL_CUTOFF_TIME:
            nearby_enemies = self.bot.enemy_units.filter(
                lambda u: not u.is_flying
                and self.enemy.can_be_attacked(u, self.enemy.get_recent_enemies())
            )
            for worker in self.bot.workers:
                if worker.health_percentage > MN.WORKER_ATTACK_NEARBY_RETREAT_HEALTH_PERCENT_THRESHOLD:
                    close_enemies = cy_closer_than(nearby_enemies, MN.WORKER_ATTACK_NEARBY_ENEMY_RANGE, worker.position)
                    if close_enemies:
                        worker.attack(cy_closest_to(worker.position, close_enemies))
            self._release_non_defenders(defender_tags)
            return

        worker_rush_detected = self.tactics.is_active(Tactic.WORKER_RUSH_DEFENCE)
        if worker_rush_detected:
            if self.use_cool_defense or self.bot.enemy_units.closer_than(30, self.bot.start_location).amount >= 2:
                if not self.use_cool_defense:
                    await LogHelper.add_chat("Worker rush detected, activating cool defense")
                    self.use_cool_defense = True
                await self.cool_worker_rush_defense()
            else:
            # self.defend_worker_rush_wicked(self.bot)
                self.do_worker_rush_defense()
            return

        # defend vs workers that are short of a full worker rush
        # ── Phase 1: Select fighters ────────────────────────────────────
        available_workers = self.bot.workers.filter(
            lambda u: self.assignments_by_worker[u.tag].job_type != WorkerJobType.SCOUT
        )
        healthy_workers = available_workers.filter(lambda u: u.health > MN.WORKER_ATTACK_RETREAT_HEALTH_THRESHOLD)
        unhealthy_workers = available_workers.filter(lambda u: u.health <= MN.WORKER_ATTACK_RETREAT_HEALTH_THRESHOLD)

        targetable_enemies = self.bot.enemy_units.filter(
            lambda u: not u.is_flying
            and self.enemy.can_be_attacked(u, self.enemy.get_recent_enemies())
            and u.position.manhattan_distance(self.bot.start_location) < MN.WORKER_ATTACK_PULL_ENEMY_RANGE
        )
        valid_enemy_structures = self.bot.enemy_structures.filter(
            lambda u: not u.is_ready or u.type_id not in {UnitTypeId.BUNKER, UnitTypeId.PHOTONCANNON}
        )
        nearby_enemy_structures = cy_closer_than(valid_enemy_structures,
                                                 MN.WORKER_ATTACK_PULL_ENEMY_RANGE,
                                                 self.bot.start_location)
        targetable_enemies.extend(nearby_enemy_structures)

        enemies_inside_wall = self.filter_enemies_outside_wall(targetable_enemies)
        total_worker_count = len(available_workers)
        max_workers_to_send = min(total_worker_count - MN.WORKER_ATTACK_PULL_RESERVE_MINERS,
                                  len(enemies_inside_wall) + MN.WORKER_ATTACK_PULL_EXTRA_DEFENDERS)
        self.min_workers_to_keep_on_minerals = total_worker_count - max_workers_to_send

        self.units_to_attack = set(
            self.filter_enemies_outside_wall(Units(self.units_to_attack, bot_object=self.bot))
        )

        assigned_defender_counts: Dict[int, int] = defaultdict(int)

        # — per-worker enemy proximity check (same selection logic) —
        for worker in self.bot.workers:
            assignment = self.assignments_by_worker[worker.tag]
            if assignment.job_type in (WorkerJobType.SCOUT, WorkerJobType.IDLE):
                continue

            worker_is_outside_wall = self.is_outside_wall(worker)
            enemies_for_worker = targetable_enemies if worker_is_outside_wall else enemies_inside_wall
            position = assignment.target if assignment.target else worker
            nearby_enemies = cy_closer_than(enemies_for_worker, MN.WORKER_ATTACK_NEARBY_ENEMY_RANGE_WORKER_RUSH, position.position)

            if nearby_enemies:
                # builders: stop & fight only if melee-range and healthy
                if assignment.job_type == WorkerJobType.BUILD:
                    closest_enemy = cy_closest_to(worker.position, nearby_enemies)
                    if closest_enemy.distance_to_squared(worker) < 4:
                        if worker.is_constructing_scv:
                            worker(AbilityId.HALT)
                        if worker.health > MN.WORKER_ATTACK_RETREAT_HEALTH_THRESHOLD and len(nearby_enemies) == 1:
                            assignment.on_attack_break = True
                            assigned_defender_counts[closest_enemy.tag] += 1
                            defender_tags.add(worker.tag)
                    if cy_distance_to(worker.position, self.bot.start_location) > 8:
                        # wait until worker is near base to send other workers over to fight
                        continue

                if len(nearby_enemies) >= len(available_workers) and not worker_rush_detected:
                    continue

                for nearby_enemy in nearby_enemies:
                    num_defenders_per_enemy = 2 if nearby_enemy.type_id in UnitTypes.WORKER_TYPES else 3
                    needed = num_defenders_per_enemy - assigned_defender_counts[nearby_enemy.tag]
                    if needed > 0:
                        predicted_position = self.enemy.get_predicted_position(nearby_enemy, 2.0)
                        new_defenders = self._select_defenders(
                            predicted_position, healthy_workers, unhealthy_workers, needed
                        )
                        assigned_defender_counts[nearby_enemy.tag] += len(new_defenders)
                        defender_tags.update(new_defenders)

        # only defend base area against single workers and structures
        if len(nearby_enemy_structures) > 0 or targetable_enemies(UnitTypes.WORKER_TYPES).amount <= 3:
            LogHelper.add_log(f"Defending base against {len(targetable_enemies)} nearby enemies")
            # — base / ramp defense —
            for townhall in self.bot.townhalls:
                defender_tags.update(
                    self._select_position_defenders(
                        townhall, 18, assigned_defender_counts,
                        healthy_workers, unhealthy_workers,
                        worker_rush_detected, enemies_inside_wall,
                    )
                )
            defender_tags.update(
                self._select_position_defenders(
                    self.bot.main_base_ramp.top_center, 3, assigned_defender_counts,
                    healthy_workers, unhealthy_workers,
                    worker_rush_detected, enemies_inside_wall,
                )
            )

        # ── Phase 2: Control fighters ───────────────────────────────────
        fighters = UnitReferenceHelper.get_updated_units_by_tag(defender_tags)
        await self._control_fighters(fighters, targetable_enemies, enemies_inside_wall)

        # release any workers no longer needed
        self._release_non_defenders(defender_tags)

    # ─── Phase-1 helpers ────────────────────────────────────────────────

    def _select_defenders(
        self,
        target_position: Point2,
        healthy_workers: Units,
        unhealthy_workers: Units,
        count: int,
    ) -> set[int]:
        """Pick *count* closest workers (prefer healthy) without sending them
        from far away. Returns their tags."""
        count = min(count, len(healthy_workers) + len(unhealthy_workers) - self.min_workers_to_keep_on_minerals)
        tags: set[int] = set()
        pools = [healthy_workers, unhealthy_workers]
        for pool in pools:
            if count <= 0:
                break
            available = pool.closest_n_units(target_position, min(count, len(pool))) if pool else Units([], self.bot)
            for worker in available:
                dist_sq = cy_distance_to_squared(worker.position, target_position)
                height_diff = abs(
                    self.bot.get_terrain_height(worker.position)
                    - self.bot.get_terrain_height(target_position)
                )
                if dist_sq > MN.WORKER_ATTACK_PULL_RANGE_SQ or height_diff > MN.WORKER_ATTACK_PULL_HEIGHT_RANGE:
                    continue
                tags.add(worker.tag)
                pool.remove(worker)
                self.assignments_by_worker[worker.tag].on_attack_break = True
                count -= 1
        return tags

    def _select_position_defenders(
        self,
        position: Point2 | Unit,
        radius: float,
        assigned_defender_counts: Dict[int, int],
        healthy_workers: Units,
        unhealthy_workers: Units,
        worker_rush_detected: bool,
        nearby_enemies: Units | list[Unit],
    ) -> set[int]:
        """Select defenders for a base / ramp — mirrors old defend_position
        selection logic but only selects (does not issue orders)."""
        defender_tags: set[int] = set()
        valid_enemy_structures = self.bot.enemy_structures.filter(
            lambda u: not u.is_ready or u.type_id not in {UnitTypeId.BUNKER, UnitTypeId.PHOTONCANNON}
        )
        nearby_enemy_structures = cy_closer_than(valid_enemy_structures,
                                                 MN.WORKER_ATTACK_PULL_ENEMY_RANGE,
                                                 position.position)
        if nearby_enemy_structures:
            nearby_enemy_structures.sort(
                key=lambda a: (a.type_id != UnitTypeId.PHOTONCANNON) * 1_000_000
                + cy_distance_to_squared(a.position, position.position)
            )

        nearby_enemies_list = cy_closer_than(nearby_enemies, radius, position.position)
        radius_sq = radius * radius
        for enemy in self.units_to_attack:
            if enemy.type_id == UnitTypeId.BUNKER and enemy.build_progress == 1.0:
                continue
            predicted = self.enemy.get_predicted_position(enemy, 0.0)
            if cy_distance_to_squared(predicted, position.position) < radius_sq:
                nearby_enemies_list.append(enemy)

        workers_per_enemy = MN.WORKER_ATTACK_PER_ENEMY
        if self.bot.enemy_race == Race.Protoss and len(nearby_enemy_structures) == 0:
            workers_per_enemy = MN.WORKER_ATTACK_PER_PROBE_NO_STRUCTURES
        all_nearby = nearby_enemies_list
        all_nearby.extend(nearby_enemy_structures)
        for nearby_enemy in all_nearby:
            closest_friendly = cy_closest_to(nearby_enemy.position, self.bot.workers)
            enemy_position = nearby_enemy.position
            if not cy_is_facing(nearby_enemy, closest_friendly, MN.IS_FACING_ANGLE_ERROR):
                # use predicted position if enemy is running away to try to cut them off
                enemy_position = self.enemy.get_predicted_position(nearby_enemy,
                                                                   MN.WORKER_ATTACK_ENEMY_PREDICTION_SECONDS)
            target_count = 4 if nearby_enemy.is_structure else workers_per_enemy
            needed = target_count - assigned_defender_counts[nearby_enemy.tag]
            if needed > 0:
                new_tags = self._select_defenders(
                    enemy_position, healthy_workers, unhealthy_workers, needed
                )
                if not new_tags:
                    break
                assigned_defender_counts[nearby_enemy.tag] += len(new_tags)
                defender_tags.update(new_tags)
        return defender_tags

    # ─── Phase-2: control fighters ──────────────────────────────────────

    async def _control_fighters(
        self,
        fighters: Units,
        targetable_enemies: Units,
        enemies_inside_wall: Units,
    ) -> None:
        """Issue orders for every selected fighter.

        Priority per worker:
          1. Retreat (mineral walk home) if below RETREAT_HEALTH.
          2. Attack an enemy in or near range.
          3. Repair a nearby injured friendly worker.
          4. Move / mineral-walk toward the enemy.
        """
        out_of_range_healthy: List[Unit] = []
        in_range_healthy: List[Unit] = []
        in_range_unhealthy: List[Unit] = []
        out_of_range_unhealthy: List[Unit] = []
        healers_assigned: Set[int] = set()
        closest_enemies: Dict[int, Unit] = {}
        for fighter in fighters:
            if fighter.is_carrying_resource:
                # deliver resources before fighting so mineral walking will work
                if self.bot.townhalls:
                    fighter.smart(cy_closest_to(fighter.position, self.bot.townhalls))
                continue
            assignment = self.assignments_by_worker[fighter.tag]
            if assignment.job_type == WorkerJobType.BUILD:
                continue
            worker_is_outside_wall = self.is_outside_wall(fighter)
            enemies_for_fighter = targetable_enemies if worker_is_outside_wall else enemies_inside_wall
            if not enemies_for_fighter:
                continue
            if self.worker_micro._avoid_effects(fighter, False) != UnitMicroType.NONE:
                continue
            is_healthy = fighter.health > MN.WORKER_ATTACK_RETREAT_HEALTH_THRESHOLD
            closest_enemy = cy_closest_to(fighter.position, enemies_for_fighter)
            closest_enemies[fighter.tag] = closest_enemy
            is_near_enemy = cy_distance_to_squared(fighter.position, closest_enemy.position) < self.enemy.get_attack_range_with_buffer_squared(fighter, closest_enemy, attack_range_buffer=1.0)

            if is_healthy:
                if is_near_enemy:
                    in_range_healthy.append(fighter)
                else:
                    out_of_range_healthy.append(fighter)
            else:
                if is_near_enemy:
                    in_range_unhealthy.append(fighter)
                else:
                    out_of_range_unhealthy.append(fighter)

        fight_is_started = len(in_range_healthy) + len(in_range_unhealthy) > 0

        for fighter in in_range_healthy:
            closest_enemy = closest_enemies[fighter.tag]
            closest_enemy_distance = cy_distance_to(fighter.position, closest_enemy.position)

            # recruit a healer that is further from the enemy than the fighter and be near it before attacking
            healer_candidates = []
            for unit_pool in [out_of_range_healthy, out_of_range_unhealthy]:
                healer_candidates = [
                    u for u in unit_pool
                    if u.tag not in healers_assigned
                    and cy_distance_to(u.position, closest_enemy.position) > closest_enemy_distance
                ]
                if healer_candidates:
                    break
            if healer_candidates:
                closest_healer = cy_closest_to(fighter.position, healer_candidates)
                healers_assigned.add(closest_healer.tag)
                if fighter.health_percentage < 1.0:
                    closest_healer.repair(fighter)
                else:
                    closest_healer.move(fighter)

            # attack enemy
            nearby_enemies = Units(
                cy_closer_than(targetable_enemies, closest_enemy_distance + 0.1, fighter.position), bot_object=self.bot
            )
            attack_target = min(nearby_enemies, key=lambda u: u.health + u.shield)
            fighter.attack(attack_target)

        for fighter in out_of_range_healthy:
            if fighter.tag in healers_assigned:
                continue

            closest_enemy = closest_enemies[fighter.tag]
            closest_enemy_distance = cy_distance_to(fighter.position, closest_enemy.position)
            if not fight_is_started:
                # recruit a healer that is further from the enemy than the fighter and be near it before attacking
                healer_candidates = []
                for unit_pool in [out_of_range_healthy, out_of_range_unhealthy]:
                    healer_candidates = [
                        u for u in unit_pool
                        if u.tag not in healers_assigned
                        and cy_distance_to(u.position, closest_enemy.position) > closest_enemy_distance
                    ]
                    if healer_candidates:
                        break
                if healer_candidates:
                    closest_healer = cy_closest_to(fighter.position, healer_candidates)
                    healers_assigned.add(closest_healer.tag)
                    if fighter.health_percentage < 1.0:
                        closest_healer.repair(fighter)
                    else:
                        closest_healer.move(fighter)
                    if cy_distance_to(fighter.position, closest_healer.position) > 1.0:
                        fighter.move(closest_healer)
                        continue

            # XXX consider mineral-walking
            fighter.attack(closest_enemy)

        for fighter in in_range_unhealthy:
            # run away
            self._mineral_walk_retreat(fighter)

        for fighter in out_of_range_unhealthy:
            closest_enemy = closest_enemies[fighter.tag]
            enemy_distance = cy_distance_to(fighter.position, closest_enemy.position)
            # run further away
            if enemy_distance < MN.WORKER_ATTACK_MINERAL_WALK_RETREAT_DISTANCE:
                self._mineral_walk_retreat(fighter)
            elif fight_is_started:
                nearby_friendlies = Units(
                    cy_closer_than(fighters, MN.WORKER_ATTACK_INJURED_REPAIR_NEARBY_RANGE, fighter.position), bot_object=self.bot
                ).filter(
                    lambda u: u.tag != fighter.tag
                    and u.health_percentage < 1.0
                    and u.is_mechanical
                )
                if nearby_friendlies and self.bot.minerals >= MN.WORKER_REPAIR_MIN_MINERALS:
                    repair_target = cy_closest_to(fighter.position, nearby_friendlies)
                    fighter.repair(repair_target)

    def defend_worker_rush_wicked(self, bot: BotAI) -> None:
        if (not bot.workers or not bot.enemy_units):
            return

        main_position: Point2 = bot.start_location
        enemy_main_position: Point2 = bot.enemy_start_locations[0]

        retreat_minerals: Units = bot.mineral_field.closer_than(12, main_position)
        attack_minerals: Units = bot.mineral_field.closer_than(12, enemy_main_position)
        if (not retreat_minerals or not attack_minerals):
            return

        # Mineral at main closest to the enemy base — used as a safe kiting gather point
        mineral_field_main: Unit = retreat_minerals.closest_to(enemy_main_position)
        # Mineral at enemy main closest to our base — used to kite enemy workers away
        mineral_field_enemy: Unit = attack_minerals.closest_to(main_position)

        enemy_units: Units = bot.enemy_units.sorted(
            lambda unit: (unit.health + unit.shield, unit.distance_to(main_position))
        )
        best_potential_targets: Units = enemy_units.take(3)

        for worker in bot.workers:
            assignment = self.assignments_by_worker[worker.tag]
            assignment.on_attack_break = True
            enemies_in_range: Units = bot.enemy_units.in_attack_range_of(worker).sorted(lambda unit: (unit.health + unit.shield))
            best_target: Unit = (
                enemies_in_range.first if enemies_in_range else
                best_potential_targets.closest_to(worker)
            )

            if worker.weapon_cooldown < 6:
                distance: float = worker.distance_to(best_target)

                if worker.target_in_range(best_target):
                    worker.attack(best_target)
                elif distance > 3:
                    worker.move(best_target.position.towards(worker, -1))
                else:
                    # Side-step to a mineral patch to reset weapon animation safely
                    if worker.distance_to(mineral_field_enemy) > best_target.distance_to(mineral_field_enemy):
                        worker.gather(mineral_field_enemy)
                    elif worker.distance_to(mineral_field_main) > best_target.distance_to(mineral_field_main):
                        worker.gather(mineral_field_main)
                    else:
                        worker.move(worker.position.towards(best_target, -1))
            else:
                # On cooldown: gather to keep mining and avoid eating free hits
                worker.gather(mineral_field_main)

    enemies_have_entered: bool = False
    ramp_is_secured: bool = False
    circle_positions: list[Point2] = []
    first_position_index: int = 0
    furthest_from_ramp_index: int = 0
    furthest_point_reached: bool = False
    worker_track_progress: Dict[int, int] = defaultdict(int)  # track which position in the circle each worker is at for kiting
    kiting_worker: Unit | None = None
    circle_increment: int = 1
    trapped_enemy_tags: set[int] = set()  # track which enemy workers we've successfully trapped at the ramp to focus fire on them
    escaped_enemy_tags: set[int] = set()  # track which enemy workers we've successfully trapped at the ramp to focus fire on them
    ramp_guards: Units | None = None
    in_position_guard_tags: set[int] = set()  # track which workers are in position at the ramp to hold it
    repair_targets: Dict[int, int] = {}

    async def cool_worker_rush_defense(self) -> None:
        """blow some minds. circle around the enemy workers and blockade the ramp to fight. lift the main base and fly it to the natural, retreat to natural, enemy will try to retreat down the ramp and die"""
        if not self.enemies_have_entered:
            for e in self.bot.enemy_units:
                if cy_distance_to_squared(self.bot.main_base_ramp.top_center, e.position) < 9 or cy_distance_to_squared(self.bot.start_location, e.position) < 225:
                    self.enemies_have_entered = True
                    await LogHelper.add_chat(f"Worker rush defense: enemies have entered base")
                    break

            # halt early builds to not risk having a second worker at the ramp that might lead enemies away from the kiter
            if self.bot.time < 60:
                for worker in self.bot.workers:
                    if worker.is_constructing_scv:
                        await LogHelper.add_chat(f"Worker {worker.tag} is constructing, halting to prepare for rush")
                        worker(AbilityId.HALT)
        else:
            # fly base to natural if enough enemies to warrant moving base
            if len(self.trapped_enemy_tags) > 6:
                main_base = self.bot.townhalls.closest_to(self.bot.start_location)
                if main_base.position == self.map.natural_position:
                    if main_base.is_flying:
                        LogHelper.add_log("Landing main base to fight worker rush at natural")
                        main_base(AbilityId.LAND, self.map.natural_position)
                else:
                    if main_base.is_flying:
                        main_base.move(self.map.natural_position)
                    else:
                        LogHelper.add_log("Lifting main base to reposition against worker rush")
                        main_base(AbilityId.LIFT)

            # circle workers around to cut off ramp 
            if not self.ramp_is_secured and not self.enemy_exit_started:
                await self.secure_ramp()
            else:
                await self.fight_at_ramp()

    async def secure_ramp(self):
        enemies_to_entrap = self.bot.enemy_units.closer_than(30, self.bot.start_location)
        ramp_guard_count = self.bot.workers.amount
        if enemies_to_entrap.amount <= 6:
            # + 1 is for the kiting worker
            ramp_guard_count = max(2, enemies_to_entrap.amount // 2) + 1
        await LogHelper.add_chat(f"Securing ramp against worker rush, {enemies_to_entrap.amount} enemies to entrap, assigning {ramp_guard_count} workers to guard ramp")
        defenders_at_ramp = self.bot.workers.closer_than(4, self.bot.main_base_ramp.bottom_center)
        if self.kiting_worker:
            defenders_at_ramp = defenders_at_ramp.filter(lambda w: w != self.kiting_worker)

        self.trapped_enemy_tags = self.trapped_enemy_tags.union(self.bot.enemy_units.tags)
        if defenders_at_ramp.amount >= max(1, ramp_guard_count - 2):
            self.ramp_is_secured = True
            # self.kiting_worker = None
            self.worker_track_progress.clear()
            # self.enemies_have_entered = False
            await LogHelper.add_chat(f"Secured ramp against worker rush with {defenders_at_ramp.amount} defenders")
            self.tactics.set_active(Tactic.RAMP_SECURED, True)
        else:
            if self.kiting_worker:
                try:
                    self.kiting_worker = UnitReferenceHelper.get_updated_unit(self.kiting_worker)
                except Exception as e:
                    # destroyed
                    self.kiting_worker = None
            if self.kiting_worker is None:
                self.kiting_worker = self.bot.workers.closest_to(self.bot.main_base_ramp.top_center)

            if len(self.circle_positions) == 0:
                self.generate_circle_positions()
            
                # circle clockwise if kiting worker is closer to the first clockwise position to start
                other_direction_first_index = (self.first_position_index - 1) % len(self.circle_positions)
                if cy_distance_to_squared(self.kiting_worker.position, self.circle_positions[self.first_position_index]) \
                    > cy_distance_to_squared(self.kiting_worker.position, self.circle_positions[other_direction_first_index]):
                    self.first_position_index = other_direction_first_index
                    self.circle_increment = -1

            self.ramp_guards = self.bot.workers.sorted(
                    lambda w: w.distance_to_squared(self.bot.start_location), reverse=True
                ).take(ramp_guard_count)
            
            for worker in self.bot.workers:
                assignment = self.assignments_by_worker[worker.tag]
                closest_enemy = cy_closest_to(worker.position, self.bot.enemy_units) if self.bot.enemy_units else None
                assignment.on_attack_break = True
                if worker.is_constructing_scv:
                    await LogHelper.add_chat(f"Worker {worker.tag} is constructing, halting to secure ramp")
                    worker(AbilityId.HALT)
                elif worker in self.ramp_guards and worker.tag in self.worker_track_progress:
                    current_index = self.worker_track_progress[worker.tag]
                    if worker.tag not in self.in_position_guard_tags:
                        if cy_distance_to_squared(worker.position, self.bot.main_base_ramp.bottom_center) < 4:
                            await LogHelper.add_chat(f"guard {worker.tag} is securing the ramp")
                            self.in_position_guard_tags.add(worker.tag)
                            # set this to catch returing scouts that don't need to circle the main
                            current_index = self.first_position_index
                    if current_index == self.first_position_index:
                        if worker.tag in self.in_position_guard_tags and closest_enemy and cy_distance_to_squared(worker.position, closest_enemy.position) < 4:
                            worker.attack(closest_enemy)
                        else:
                            worker.move(self.bot.main_base_ramp.bottom_center)
                    else:
                        if worker.tag == self.kiting_worker.tag:
                            if current_index == self.furthest_from_ramp_index:
                                await LogHelper.add_chat("kiting worker has reached the furthest point from the ramp")
                                self.furthest_point_reached = True
                            if closest_enemy and cy_distance_to_squared(worker.position, closest_enemy.position) > 25:
                                # move toward enemy to try to aggro them
                                worker.move(closest_enemy.position)
                                continue
                        next_position = self.circle_positions[current_index]
                        if worker.distance_to(next_position) < 2:
                            current_index = (current_index + self.circle_increment) % len(self.circle_positions)
                            self.worker_track_progress[worker.tag] = current_index
                            next_position = self.circle_positions[current_index]
                        worker.move(next_position)
                else:
                    # assign initial starting positions for circling around
                    if worker.tag == self.kiting_worker.tag:
                        current_index = (self.first_position_index + self.circle_increment) % len(self.circle_positions)
                        initial_index = current_index
                        first_position = self.circle_positions[current_index]
                        worker_distance = cy_distance_to(worker.position, first_position)
                        # find first position that is away from enemies
                        while cy_closer_than(self.bot.enemy_units, worker_distance, first_position):
                            current_index = (current_index + self.circle_increment) % len(self.circle_positions)
                            first_position = self.circle_positions[current_index]
                            worker_distance = cy_distance_to(worker.position, first_position)
                            if current_index == initial_index:
                                # all positions are too close to enemies, just pick the first one
                                break
                        worker.move(first_position)
                        self.worker_track_progress[worker.tag] = current_index
                        LogHelper.add_log(f"Worker {worker.tag} kiting around to ramp starting from {worker.position}")
                    elif worker in self.ramp_guards:
                        if self.bot.enemy_units:
                            for guard in self.ramp_guards:
                                if guard.tag in self.worker_track_progress and guard != self.kiting_worker:
                                    self.worker_track_progress[worker.tag] = self.worker_track_progress[guard.tag]
                                    break
                            else:
                                position_to_avoid = self.bot.main_base_ramp.top_center
                                away_from_ramp = max(self.circle_positions, key=lambda p: cy_distance_to_squared(p, position_to_avoid))
                                LogHelper.add_log(f"Worker {worker.tag} circling around to ramp starting from {away_from_ramp}")
                                current_index = self.circle_positions.index(away_from_ramp)
                                self.worker_track_progress[worker.tag] = (current_index + self.circle_increment * 2) % len(self.circle_positions)
                        else:
                            self.worker_track_progress[worker.tag] = self.first_position_index
                            worker.move(self.circle_positions[self.first_position_index])
                    elif self.furthest_point_reached and closest_enemy:
                        worker.attack(closest_enemy)
                    else:
                        assignment.on_attack_break = False

    def generate_circle_positions(self):
        # generate circle positions around the main base, similar to scouting positions
        # kiting worker will start by moving to the position nearest the ramp then move counter-clockwise
        # other workers will move to the position that is directly away from the nearest enemy to them, then follow the circle
        # when they reach the ramp they will go down it and wait at the bottom for the next stage
        radius = 13
        base_to_ramp_angle_radians = self.get_facing(self.bot.start_location, self.bot.main_base_ramp.top_center)
        angle_increments = 15
        radian_increments = math.radians(angle_increments)
        furthest_distance_from_ramp = 0
        for angle_degrees in range(0, 360, angle_increments):
            angle_radians = math.radians(angle_degrees)
            if angle_radians >= base_to_ramp_angle_radians and angle_radians < base_to_ramp_angle_radians + radian_increments:
                self.first_position_index = len(self.circle_positions)
            x_offset = radius * math.cos(angle_radians)
            y_offset = radius * math.sin(angle_radians)
            waypoint = Point2((self.bot.start_location.x + x_offset, self.bot.start_location.y + y_offset))
            retries = 0
            while not cy_in_pathing_grid_burny(self.bot.game_info.pathing_grid.data_numpy, waypoint) and retries < 5:
                waypoint = Point2(cy_towards(waypoint, self.bot.start_location, 1))
                retries += 1
            if retries != 5:
                distance_from_ramp = cy_distance_to_squared(waypoint, self.bot.main_base_ramp.top_center)
                if distance_from_ramp > furthest_distance_from_ramp:
                    furthest_distance_from_ramp = distance_from_ramp
                    self.furthest_from_ramp_index = len(self.circle_positions)

                self.circle_positions.append(waypoint)
    
        # circle clockwise if kiting worker is closer to the first clockwise position to start
        other_direction_first_index = (self.first_position_index - 1) % len(self.circle_positions)
        if self.kiting_worker and \
            cy_distance_to_squared(self.kiting_worker.position, self.circle_positions[self.first_position_index]) \
            > cy_distance_to_squared(self.kiting_worker.position, self.circle_positions[other_direction_first_index]):
            self.first_position_index = other_direction_first_index
            self.circle_increment = -1

    enemy_exit_started: bool = False
    async def fight_at_ramp(self):
        main_base_height = self.bot.get_terrain_height(self.bot.main_base_ramp.top_center)

        enemies_outside_main = self.bot.enemy_units.filter(lambda u: self.bot.get_terrain_height(u) < main_base_height and cy_distance_to(u.position, self.map.natural_position) < 20)
                                                    #   and self.position_is_between(u.position, self.bot.main_base_ramp.barracks_in_middle, base_exit)) # type: ignore

        # don't count extra workers reaching the bottom of the ramp as starting the exit
        for u in self.bot.enemy_units:
            if u.tag in self.trapped_enemy_tags and cy_distance_to_squared(u.position, self.bot.main_base_ramp.top_center) < 4:
                self.escaped_enemy_tags.add(u.tag)
                if not self.enemy_exit_started:
                    self.enemy_exit_started = True
                    await LogHelper.add_chat("enemy exit started")
                    break

        landed_townhalls = self.bot.structures(UnitTypeId.COMMANDCENTER)
        repositioned_to_natural = len(cy_closer_than(landed_townhalls, 5, self.map.natural_position)) > 0
        self.trapped_enemy_tags = set([tag for tag in self.trapped_enemy_tags if self.tactics.enemy.enemy_is_alive(tag)])
        if enemies_outside_main.amount == 0 and (repositioned_to_natural or len(self.trapped_enemy_tags) == 0):
            await LogHelper.add_chat("no nearby enemies, releasing workers")
            # workers_to_release = self.bot.workers.sorted(lambda w: not w.is_carrying_resource)[:self.bot.workers.amount // 2]
            for worker in self.bot.workers:
                self.assignments_by_worker[worker.tag].on_attack_break = False
            if not repositioned_to_natural:
                # reset back to main base and prepare to repeat
                await LogHelper.add_chat("enemies gone, resetting to secure ramp again if needed")
                self.enemies_have_entered = False
                self.ramp_is_secured = False
            return
        
        new_enemy_tags = enemies_outside_main.tags - self.trapped_enemy_tags
        if len(new_enemy_tags) > 3:
            await LogHelper.add_chat(f"new enemy wave {new_enemy_tags}")
            self.ramp_is_secured = False
            self.kiting_worker = None
            self.enemy_exit_started = False
            return

        # Mineral at main closest to the enemy base — used as a safe kiting gather point
        if not self.bot.mineral_field:
            return
        main_mineral_field: Unit = self.bot.mineral_field.closest_to(self.bot.start_location)
        natural_mineral_field: Unit = self.bot.mineral_field.closest_to(self.map.natural_position)

        injured_workers = self.bot.workers.filter(lambda w: w.health <= 20)
        if not self.enemy_exit_started:
            injured_workers = injured_workers.filter(lambda w: w != self.kiting_worker)

        if self.ramp_guards is None:
            self.ramp_guards = self.bot.workers.closer_than(4, self.bot.main_base_ramp.bottom_center)

        enemy_health = 0
        units_to_attack = self.bot.enemy_units if self.enemy_exit_started else enemies_outside_main
        enemy_health = sum([u.health + u.shield for u in units_to_attack])
        # only use enough guards to kill enemies (don't chase a 6hp enemy with 13 workers)
        attackers_needed = int((enemy_health - 1) // 5 + 1)
        attackers = self.bot.workers
        if 0 < attackers_needed < self.bot.workers.amount:
            attackers = attackers.sorted(lambda w: w.health, reverse=True).take(attackers_needed)

        if self.bot.minerals < MN.WORKER_REPAIR_MIN_MINERALS:
            self.repair_targets.clear()

        for worker in self.bot.workers:
            assignment = self.assignments_by_worker[worker.tag]
            assignment.on_attack_break = True
            enemies_in_range: Units = self.bot.enemy_units.in_attack_range_of(worker, 0.1).sorted(lambda unit: (unit.health + unit.shield))

            if worker.weapon_cooldown >= 6:
                # On cooldown: gather to phase away to make room for workers that are off cooldown and to avoid taking hits
                worker.gather(natural_mineral_field)
            else:
                if self.do_worker_repair(worker, 10, 20):
                    continue
                elif worker.health <= 10:
                    assignment.on_attack_break = False
                    continue

                if self.enemy_exit_started:
                    # enemy is trying to escape ramp, now is the chance to kill them
                    if worker == self.kiting_worker:
                        if cy_distance_to_squared(worker.position, self.bot.main_base_ramp.bottom_center) <= 3:
                            # clear assignment once it reaches the ramp
                            self.kiting_worker = None
                        else:
                            worker.gather(natural_mineral_field)
                    elif enemies_in_range:
                        # attack anything in range if able
                        worker.attack(enemies_in_range.first)
                    elif enemies_outside_main.amount > 0 and worker in attackers:
                        closest_enemy = cy_closest_to(worker.position, enemies_outside_main)
                        worker.attack(closest_enemy)
                    elif self.bot.enemy_units.amount > 0 and worker in attackers:
                        # might be mostly dead code due to earlier return when no enemies_outside_main, but doesn't hurt
                        closest_enemy = cy_closest_to(worker.position, self.bot.enemy_units)
                        LogHelper.add_log(f"Worker at {worker.position} ({worker.health} HP) attacking any unit")
                        worker.attack(closest_enemy)
                    else:
                        # no enemies left
                        assignment.on_attack_break = False
                        if not repositioned_to_natural:
                            # reset back to main base and prepare to repeat
                            await LogHelper.add_chat("enemies gone 2, resetting to secure ramp again if needed")
                            self.enemies_have_entered = False
                            self.ramp_is_secured = False
                else:
                    # waiting for enemy to exit, stack on ramp, repair up, and ward off any extra enemies that arrive
                    if worker == self.kiting_worker:
                        worker.gather(natural_mineral_field)
                        continue
                    if enemies_in_range and worker != self.kiting_worker:
                        # attack anything in range, except for kiting worker which will die if it turns to attack
                        worker.attack(enemies_in_range.first)
                        continue
                    if worker.tag not in self.ramp_guards.tags and self.bot.enemy_units.amount > 0:
                        # send a few units to attack new arrivals but don't send all and leave ramp unguarded
                        closest_enemy = cy_closest_to(worker.position, self.bot.enemy_units)
                        worker.attack(closest_enemy)
                        continue
                    if enemies_outside_main.amount > 0:
                        # send a few units to attack new arrivals but don't send all and leave ramp unguarded
                        closest_enemy = cy_closest_to(worker.position, enemies_outside_main)
                        if cy_distance_to(closest_enemy.position, self.bot.main_base_ramp.bottom_center) < 5:
                            closest_defenders = self.bot.workers.closest_n_units(closest_enemy.position, enemies_outside_main.amount + 2)
                            if worker in closest_defenders:
                                worker.attack(closest_enemy)
                                continue
                    if self.position_is_between(self.bot.main_base_ramp.bottom_center, worker.position, self.bot.main_base_ramp.top_center):
                        # no injured, just muster at bottom of ramp by alternating between patches
                        LogHelper.add_log(f"Worker at {worker.position} ({worker.health} HP) gathering at main")
                        worker.gather(main_mineral_field)
                    else:
                        worker.gather(natural_mineral_field)
                
    def do_worker_rush_defense(self, base_location: Point2 | None = None) -> None:
        if base_location is None:
            base_location = self.bot.start_location
        enemy_units: Units = self.bot.enemy_units.sorted(
            lambda unit: (unit.health + unit.shield, unit.distance_to(base_location))
        )
        best_potential_targets: Units = enemy_units.take(3)

        enemy_main_position: Point2 = self.bot.enemy_start_locations[0]

        enemies_in_base = Units(cy_closer_than(enemy_units, 25, base_location), bot_object=self.bot)
        enemy_count = enemies_in_base.amount
        if enemy_count == 0:
            return
        response_workers = self.bot.workers
        if enemy_count + 1 < response_workers.amount:
            # pick closest workers to enemies, prefering any that are over 40% hp
            sorted_workers = response_workers.sorted(lambda w: (w.shield_health_percentage < 0.4,
                                                                cy_distance_to_squared(w.position,
                                                                                       cy_closest_to(w.position, enemies_in_base).position)))
            response_workers = Units(sorted_workers[:enemy_count + 1], bot_object=self.bot)
            for worker in sorted_workers[enemy_count + 1:]:
                self.assignments_by_worker[worker.tag].on_attack_break = False

        # Mineral at main closest to the enemy base — used as a safe kiting gather point
        retreat_minerals: Units = self.bot.mineral_field.closer_than(12, base_location)
        attack_minerals: Units = self.bot.mineral_field.closer_than(12, enemy_main_position)
        if (not retreat_minerals or not attack_minerals):
            return
        # mineral_field_main: Unit = retreat_minerals.closest_to(enemy_main_position)
        mineral_field_enemy: Unit = attack_minerals.closest_to(base_location)
        base_exit = self.bot.main_base_ramp.bottom_center

        injured_workers = response_workers.filter(lambda w: w.health_percentage < 0.75)

        closest_responder = response_workers[0]
        fight_started = enemies_in_base.in_attack_range_of(closest_responder).amount > 0
        furthest_responder = response_workers[-1]
        mineral_field_main = cy_closest_to(furthest_responder.position, self.bot.mineral_field)
                  
        for worker in response_workers:
            assignment = self.assignments_by_worker[worker.tag]
            assignment.on_attack_break = True
            enemies_in_range: Units = enemies_in_base.in_attack_range_of(worker).sorted(lambda unit: (unit.health + unit.shield))
            enemies_almost_in_range: Units = enemies_in_base.in_attack_range_of(worker, 2)
            friendlies_in_range: Units = response_workers.in_attack_range_of(worker)
            best_target: Unit = (
                enemies_in_range.first if enemies_in_range else
                best_potential_targets.closest_to(worker)
            )

            other_injured = injured_workers.filter(lambda w: w.tag != worker.tag)
            if worker.weapon_cooldown < 6:
                if enemies_in_range:
                    if worker.is_constructing_scv:
                        worker(AbilityId.HALT)
                    else:
                        worker.attack(best_target)
                elif worker.health_percentage < 0.75 and other_injured:
                    closest_injured = injured_workers.closest_to(worker)
                    if worker.is_constructing_scv:
                        worker(AbilityId.HALT)
                    else:
                        worker.repair(closest_injured)
                elif not fight_started and cy_distance_to_squared(worker.position, best_target.position) > 9:
                    # keep mining or building
                    assignment.on_attack_break = False
                    # worker.move(best_target.position.towards(worker, -1))
                elif not fight_started and enemies_almost_in_range.amount > friendlies_in_range.amount:
                    # fall back to main field if outnumbered
                    if worker.is_constructing_scv:
                        worker(AbilityId.HALT)
                    else:
                        worker.gather(mineral_field_main)
                elif worker.distance_to(mineral_field_main) > worker.distance_to(base_exit):
                    # don't chase out of base
                    worker.gather(mineral_field_main)
                elif worker.distance_to(base_exit) > best_target.distance_to(base_exit):
                    # move toward enemy, which is towards the ramp
                    worker.gather(mineral_field_enemy)
                elif worker.distance_to(mineral_field_main) >= best_target.distance_to(mineral_field_main):
                    # move toward enemy, which is towards minerals
                    worker.gather(mineral_field_main)
                else:
                    # if worker is closer to both, back away to draw enemy toward the stacking line
                    worker.move(worker.position.towards(best_target, -1))
            else:
                # On cooldown: gather to keep mining and avoid eating free hits
                worker.gather(mineral_field_main)


    # ─── Mineral walking helpers ────────────────────────────────────────

    def _get_mineral_near_base(self) -> Unit | None:
        """Return a mineral patch near the start location for retreat walks."""
        if not self.bot.mineral_field:
            return None
        home_minerals = Units(
            cy_closer_than(self.bot.mineral_field, 10, self.bot.start_location),
            bot_object=self.bot,
        )
        if home_minerals:
            return home_minerals.random
        return cy_closest_to(self.bot.start_location, self.bot.mineral_field)

    _cached_enemy_natural_mineral: Unit | None = None
    _cached_enemy_natural_mineral_checked: bool = False

    def _get_enemy_natural_mineral(self) -> Unit | None:
        """Return a cached mineral patch near the enemy natural expansion."""
        if self._cached_enemy_natural_mineral_checked:
            return self._cached_enemy_natural_mineral
        self._cached_enemy_natural_mineral_checked = True
        if not self.bot.mineral_field:
            return None
        enemy_nat = self.map.enemy_natural_position
        candidates = Units(
            cy_closer_than(self.bot.mineral_field, MN.MINERAL_MAX_DISTANCE_FROM_BASE, enemy_nat),
            bot_object=self.bot,
        )
        if candidates:
            self._cached_enemy_natural_mineral = cy_closest_to(enemy_nat, candidates)
        return self._cached_enemy_natural_mineral

    def _mineral_walk_retreat(self, worker: Unit) -> None:
        """Retreat by mineral-walking toward home base minerals."""
        mineral = self._get_mineral_near_base()
        if mineral is not None:
            worker.gather(mineral)
        elif self.bot.townhalls:
            worker.move(cy_closest_to(worker.position, self.bot.townhalls).position)
        else:
            worker.move(self.bot.start_location)

    def _mineral_walk_toward_enemy(self, worker: Unit, enemy: Unit) -> bool:
        """Mineral-walk toward the enemy by targeting distant minerals.

        If the enemy is roughly between the worker and the main base ramp,
        gather the enemy-natural mineral patch — the path toward those
        distant minerals runs through the ramp area, phasing past friendlies.

        If the enemy is NOT in line with the ramp, reposition the worker so
        it will be (move perpendicular toward the worker→ramp line) before
        attempting the mineral walk.
        """
        mineral = self._get_enemy_natural_mineral()
        if mineral is None:
            worker.attack(enemy)
            return False

        ramp_top = self.bot.main_base_ramp.top_center
        # Vector from worker to ramp
        dx_ramp = ramp_top.x - worker.position.x
        dy_ramp = ramp_top.y - worker.position.y
        dist_to_ramp = max((dx_ramp ** 2 + dy_ramp ** 2) ** 0.5, 0.01)

        # Project enemy onto the worker→ramp line to check alignment
        dx_enemy = enemy.position.x - worker.position.x
        dy_enemy = enemy.position.y - worker.position.y
        # Perpendicular distance of enemy from the worker→ramp line
        cross = abs(dx_ramp * dy_enemy - dy_ramp * dx_enemy) / dist_to_ramp
        # How far along the worker→ramp line the enemy sits (positive = toward ramp)
        dot = (dx_ramp * dx_enemy + dy_ramp * dy_enemy) / dist_to_ramp

        enemy_is_inline = cross < 3.0 and dot > 0
        if enemy_is_inline:
            # Enemy is between us and the ramp — mineral walk straight through
            worker.gather(mineral)
            return True
        else:
            return False
            # # Reposition: move toward a point on the worker→ramp line that is
            # # level with the enemy (so the enemy ends up between worker and ramp)
            # reposition = Point2((
            #     worker.position.x + (dx_ramp / dist_to_ramp) * max(dot, 1.0),
            #     worker.position.y + (dy_ramp / dist_to_ramp) * max(dot, 1.0),
            # ))
            # worker.move(reposition)

    def _is_path_obstructed(self, worker: Unit, enemy: Unit) -> bool:
        """Heuristic: path is obstructed if another friendly worker sits
        between us and the enemy within a short distance."""
        dist_to_enemy = cy_distance_to(worker.position, enemy.position)
        midpoint = Point2(cy_towards(worker.position, enemy.position, min(dist_to_enemy * 0.5, 1.5)))
        nearby_friendlies = cy_closer_than(self.bot.workers, MN.WORKER_ATTACK_MINERAL_WALK_OBSTRUCTION_DISTANCE, midpoint)
        # discount self
        blocker_count = sum(1 for u in nearby_friendlies if u.tag != worker.tag)
        return blocker_count >= 1

    # ─── Cleanup ────────────────────────────────────────────────────────

    def _release_non_defenders(self, defender_tags: set[int]) -> None:
        """Put workers no longer fighting back to their previous job."""
        for worker in self.bot.workers:
            assignment = self.assignments_by_worker[worker.tag]
            if assignment.on_attack_break and worker.tag not in defender_tags:
                assignment.on_attack_break = False
                if assignment.target:
                    if assignment.unit.is_carrying_resource and self.bot.townhalls:
                        assignment.unit.smart(
                            cy_closest_to(assignment.unit.position, self.bot.townhalls)
                        )
                    else:
                        assignment.unit.smart(assignment.target)

    def filter_enemies_outside_wall(self, enemies: Units) -> Units:
        raised_depots = self.bot.structures(UnitTypeId.SUPPLYDEPOT)
        wall_raised = raised_depots.amount >= 2
        if not wall_raised:
            return enemies
        return enemies.filter(lambda u: not self.is_outside_wall(u))
    
    def is_outside_wall(self, unit: Unit) -> bool:
        return cy_distance_to_squared(unit.position, self.bot.main_base_ramp.top_center) < 9 \
                                or self.bot.get_terrain_height(unit) + 0.1 < self.bot.get_terrain_height(self.bot.main_base_ramp.top_center)

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
                        worker.smart(cy_closest_to(worker.position, self.bot.townhalls))
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
                        worker.smart(cy_closest_to(worker.position, self.bot.townhalls))
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
                    worker.smart(cy_closest_to(worker.position, self.bot.townhalls))
                else:
                    worker.smart(new_target)
            elif assignment.job_type == WorkerJobType.VESPENE:
                new_target = self.vespene.add_worker(worker)
                if new_target is None:
                    # No capacity available, keep worker idle
                    logger.warning(f"No vespene capacity for worker {worker}, keeping idle")
                    return False
                if worker.is_carrying_resource and self.bot.townhalls:
                    worker.smart(cy_closest_to(worker.position, self.bot.townhalls))
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

    def get_builder(self,
                    building_position: Point2,
                    current_builder: Unit | None = None,
                    high_priority: bool = False) -> Unit | None:
        builder = None

        if current_builder:
            current_assignment = self.assignments_by_worker[current_builder.tag]
            if not current_assignment.on_attack_break:
                return current_builder
        candidates: Units = (
            self.availiable_workers_on_job(WorkerJobType.IDLE)
            + self.availiable_workers_on_job(WorkerJobType.VESPENE)
            + self.availiable_workers_on_job(WorkerJobType.MINERALS)
            # + self.availiable_workers_on_job(JobType.REPAIR)
        )

        if not candidates:
            LogHelper.add_log(f"no builder candidates for position {building_position}")
        elif high_priority:
            builder = min(candidates,
                          key=lambda u: cy_distance_to(u.position, building_position)
                                      - cy_distance_to(u.position, cy_closest_to(u.position, self.bot.enemy_units).position)/2)
        else:
            builder = cy_closest_to(building_position, candidates)

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
            scout = cy_closest_to(position, healthy_candidates) if healthy_candidates else cy_closest_to(position, candidates)
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
    @timed_async
    async def distribute_idle(self):
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
                elif self.bot.time - self.builder_idle_time[worker.tag] < MN.BUILDER_ALLOWED_IDLE_TIME:
                    # wait before determining worker is idle
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

                if await self.minerals.add_long_distance_minerals((idle_count - reassigned_count)) > 0:
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
    async def redistribute_workers(self, remaining_resources: Cost, enemy_builds_detected: Dict[BuildType, float]) -> int:
        await self.update_repairers(enemy_builds_detected)
        await self.distribute_idle()

        remaining_cooldown = MN.WORKER_REDISTRIBUTE_COOLDOWN - (self.bot.time - self.last_worker_stop)
        if remaining_cooldown > 0:
            logger.debug(f"Distribute workers is on cooldown for {remaining_cooldown}")
            return -1

        worker_rush_active = self.tactics.is_active(Tactic.WORKER_RUSH_DEFENCE)
        max_workers_to_move = MN.WORKER_REDISTRIBUTE_MAX_COUNT
        if remaining_resources.vespene < MN.WORKER_REDISTRIBUTE_VESPENE_BANK_TARGET and not worker_rush_active:
            logger.debug("saturate vespene")
            return self.move_workers_to_vespene(max_workers_to_move)
        if remaining_resources.minerals < MN.WORKER_REDISTRIBUTE_MINERAL_BANK_TARGET or worker_rush_active:
            logger.debug("saturate minerals")
            return self.move_workers_to_minerals(max_workers_to_move)

        return 0

    @timed_async
    async def update_repairers(self, enemy_builds_detected: Dict[BuildType, float]) -> None:
        needed_repairers: int = 0
        assigned_repairers: Units = Units([], bot_object=self.bot)
        units_with_no_repairer: List[Unit] = []
        injured_units: Units = Units([], bot_object=self.bot)
        if self.bot.minerals > MN.WORKER_REPAIR_MIN_MINERALS:
            injured_units = self.units_needing_repair(enemy_builds_detected)
            if injured_units:
                # LogHelper.add_log(f"{len(injured_units)} injured units needing repair")
                missing_health = 0
                # limit to percentage of total workers
                max_repairers = min(MN.MAX_REPAIRERS,
                                    math.floor(len(self.bot.workers) * MN.WORKER_REPAIR_PERCENT_ASSIGNED))
                candidates: Units = Units([
                                worker for worker in self.bot.workers
                                if self.assignments_by_worker[worker.tag].job_type != WorkerJobType.BUILD
                                and not self.assignments_by_worker[worker.tag].on_attack_break
                            ], bot_object=self.bot)

                structure_is_injured = False
                for injured_unit in injured_units:
                    structure_is_injured = structure_is_injured or injured_unit.is_structure
                    if injured_unit.type_id == UnitTypeId.BUNKER and len(injured_unit.passengers) > 0:
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
                        if self.bot.time < MN.WORKER_REPAIR_RAMP_WALL_TIME:
                            units_with_no_repairer.append(injured_unit)

                if missing_health > 0 and self.bot.time < MN.WORKER_REPAIR_EARLY_RESPONSE_TIME and structure_is_injured:
                    # early game, just assign a bunch so wall isn't broken by a rush
                    needed_repairers = max(needed_repairers, MN.WORKER_REPAIR_EARLY_RESPONSE_COUNT)
                else:
                    needed_repairers = math.ceil(missing_health / MN.HEALTH_PER_REPAIRER)
                    if needed_repairers > max_repairers:
                        needed_repairers = max_repairers
                    else:
                        # minimum 1 repairer per injured, up to 3. mostly for repairing initial wall
                        needed_repairers = max(needed_repairers, min(MN.WORKER_REPAIR_PER_INJURED_MAX,
                                                                     len(injured_units)))
            
        current_repairers: Units = self.availiable_workers_on_job(WorkerJobType.REPAIR).filter(
            lambda u: u.tag not in assigned_repairers.tags)
        current_repair_targets = {}
        for worker in current_repairers:
            if worker.is_repairing and not worker.is_moving:
                current_repair_targets[worker.orders[0].target] = worker.tag
            elif worker.health_percentage < MN.WORKER_REPAIRER_HEALTH_PERCENT_THRESHOLD:
                self.set_as_idle(worker)
                current_repairers.remove(worker)

        repairer_shortage: int = needed_repairers - len(current_repairers)

        # remove excess repairers
        if repairer_shortage < 0:
            # LogHelper.add_log(f"removing {-repairer_shortage} excess repairers")
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

        if len(units_with_no_repairer) > MN.WORKER_REPAIR_EARLY_MAX_TARGETS:
            units_with_no_repairer = units_with_no_repairer[:MN.WORKER_REPAIR_EARLY_MAX_TARGETS]  # spread out repairers to up to 5 units, mostly to keep initial wall repaired

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
            # LogHelper.add_log(f"need {repairer_shortage} more repairers")
            candidates = self.bot.workers.filter(lambda w: 
                    self.assignments_by_worker[w.tag].job_type not in (WorkerJobType.BUILD, WorkerJobType.REPAIR)
                    and w.health_percentage > MN.WORKER_REPAIRER_HEALTH_PERCENT_THRESHOLD)
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
                repairer: Unit = cy_closest_to(unit_to_repair.position, candidates)
                if not repairer:
                    break
                if not unit_to_repair.is_structure:
                    repairer_distance = cy_distance_to(repairer.position, unit_to_repair.position)
                    if (unit_to_repair.type_id == UnitTypeId.SCV
                        and repairer_distance > MN.WORKER_REPAIR_WORKER_MAX_DISTANCE
                        or repairer_distance > MN.WORKER_REPAIR_MAX_DISTANCE
                        and self.bot.time < MN.WORKER_REPAIR_LIMIT_DISTANCE_UNTIL_TIME):
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
        
        injured_workers = self.bot.workers.filter(lambda w: 
                self.assignments_by_worker[w.tag].job_type not in (WorkerJobType.BUILD, WorkerJobType.REPAIR)
                and w.health_percentage < 1.0)
        for worker in injured_workers:
            repair_target = self.do_worker_repair(worker, 20, 45)
            if repair_target:
                self.update_assigment(worker, WorkerJobType.REPAIR, repair_target)

    def do_worker_repair(self, worker: Unit, start_health_threshold: int, stop_health_threshold: int) -> Unit | None:
        if self.bot.minerals >= MN.WORKER_REPAIR_MIN_MINERALS:
            if worker.health <= start_health_threshold and worker.tag not in self.repair_targets:
                # initiate repairing. find next lowest and repair each other
                other_injured = self.bot.workers.filter(lambda w: w.tag not in self.repair_targets and w.tag != worker.tag).sorted(lambda w: w.health)
                if other_injured:
                    repair_target = other_injured.first
                    closest_injured = cy_closest_to(worker.position, other_injured)
                    if cy_distance_to(worker.position, closest_injured.position) + 15 < cy_distance_to(worker.position, repair_target.position):
                        repair_target = closest_injured
                    worker.repair(repair_target)
                    self.repair_targets[worker.tag] = repair_target.tag
                    self.repair_targets[repair_target.tag] = worker.tag
                    return repair_target
            elif worker.tag in self.repair_targets:
                # keep repairing until both workers have at least stop_health_threshold health
                target_tag = self.repair_targets[worker.tag]
                repair_target = self.bot.workers.find_by_tag(target_tag)
                if repair_target:
                    if worker.health < stop_health_threshold or repair_target.health < stop_health_threshold:
                        worker.repair(repair_target)
                        return repair_target
                # healed or dead, remove assignments
                del self.repair_targets[worker.tag]
                del self.repair_targets[target_tag]
        return None
        
    
    async def assign_repairers_to_structure(self, injured_structure: Unit, number_of_repairers: int, candidates: Units) -> Units:
        repairers: Units = candidates.closest_n_units(injured_structure, number_of_repairers)
        assigned_count = 0
        for repairer in repairers:
            candidates.remove(repairer)
            self.update_assigment(repairer, WorkerJobType.REPAIR, injured_structure)
            if await self.worker_micro.repair(repairer, injured_structure) == UnitMicroType.REPAIR:
                assigned_count += 1
        # LogHelper.add_log(f"assigned {assigned_count} of {repairers} to repair {injured_structure}")
        return repairers

    def get_repair_target(self, repairer: Unit, injured_units: Units, units_needing_repair: list) -> Unit | None:
        other_units = injured_units.filter(lambda unit: unit.tag != repairer.tag)
        if other_units and len(units_needing_repair) > 0:
            other_units = other_units.filter(lambda unit: unit in units_needing_repair)
        new_target: Unit | None = None
        if other_units:
            new_target = cy_closest_to(repairer.position, other_units)
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
    def units_needing_repair(self, enemy_builds_detected: Dict[BuildType, float]) -> Units:
        injured_units = Units([], self.bot)
        if self.bot.workers.amount == 0:
            return injured_units
        worker_health_threshold = 1.0
        if self.tactics.is_active(Tactic.WORKER_RUSH_DEFENCE):
            worker_health_threshold = MN.WORKER_RUSH_REPAIR_WORKER_HEALTH_THRESHOLD
        has_ground_healing_shrine = MapSpecifics.has_ground_healing_shrines(self.bot)
        has_air_healing_shrine = MapSpecifics.has_air_healing_shrines(self.bot)
        for unit in self.bot.units:
            if not unit.is_mechanical:
                continue
            if unit.health_percentage == 1.0:
                continue
            if unit.type_id in {UnitTypeId.MULE, UnitTypeId.SCV}:
                continue
            if self.enemy.threats_to_repairer(unit, attack_range_buffer=0).amount > 0:
                # threats nearby, skip unless it's a sieged tank defending a base
                if unit.type_id != UnitTypeId.SIEGETANKSIEGED or not self.bot.townhalls or self.bot.townhalls.closest_distance_to(unit) >= 20:
                    continue
            # skip repairing distant units if they can just use a shrine
            closest_worker = cy_closest_to(unit.position, self.bot.workers)
            closest_worker_distance = cy_distance_to(closest_worker.position, unit.position)
            if closest_worker_distance > 30:
                if unit.is_flying and has_air_healing_shrine:
                    continue
                if not unit.is_flying and has_ground_healing_shrine:
                    continue
            injured_units.append(unit)

        # can only repair fully built structures
        if not self.tactics.is_active(Tactic.WORKER_RUSH_DEFENCE):
            for structure in self.bot.structures:
                if structure.build_progress < 1:
                    continue
                if structure.health_percentage == 1.0:
                    continue
                if structure.type_id == UnitTypeId.AUTOTURRET:
                    continue
                if self.enemy.threats_to_repairer(structure, attack_range_buffer=structure.radius*1.5).amount > 0:
                    if structure.type_id not in self.defensive_structures and \
                        (structure.type_id not in self.ramp_wall_structers or self.bot.time > MN.WORKER_REPAIR_RAMP_WALL_TIME):
                        continue
                injured_units.append(structure)
        return injured_units


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
            worker = cy_closest_to(next_node.node.position, candidates)
            candidates.remove(worker)
            self.update_assigment(worker, target_job, next_node.node)
            moved_count += 1
            resource_nodes = target.nodes_with_capacity()

        if moved_count:
            self.last_worker_stop = self.bot.time
        return moved_count

    def get_mineral_capacity(self) -> int:
        return self.minerals.get_worker_capacity()
