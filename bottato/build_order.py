import math
import random
from typing import Dict, List

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.game_data import Cost
from sc2.data import Race

from bottato.log_helper import LogHelper
from bottato.enemy import Enemy
from bottato.unit_types import UnitTypes
from bottato.build_step import BuildStep
from bottato.scv_build_step import SCVBuildStep
from bottato.upgrade_build_step import UpgradeBuildStep
from bottato.structure_build_step import StructureBuildStep
from bottato.economy.workers import Workers
from bottato.economy.production import Production
from bottato.mixins import TimerMixin, UnitReferenceMixin
from bottato.upgrades import Upgrades
from bottato.special_locations import SpecialLocations, SpecialLocation
from bottato.map.map import Map
from bottato.build_starts import BuildStarts
from bottato.counter import Counter
from bottato.enums import RushType, BuildResponseCode, WorkerJobType, BuildOrderChange


class BuildOrder(TimerMixin, UnitReferenceMixin):
    # gets processed first, for supply depots and workers
    interrupted_queue: List[BuildStep] = []
    priority_queue: List[BuildStep] = []
    # initial build order and interrupted builds
    static_queue: List[BuildStep] = []
    # dynamic queue for army units and production
    build_queue: List[BuildStep] = []
    unit_queue: List[BuildStep] = []
    started: List[BuildStep] = []
    complete: List[BuildStep] = []
    # next_unfinished_step_index: int
    tech_tree: Dict[UnitTypeId, List[UnitTypeId]] = {}
    rush_defense_enacted: bool = False
    rush_detected_type: RushType = RushType.NONE

    def __init__(self, build_name: str, bot: BotAI, workers: Workers, production: Production, map: Map):
        self.recently_completed_units: List[Unit] = []
        # self.recently_completed_transformations: List[UnitTypeId] = []
        self.recently_started_units: List[Unit] = []
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.production: Production = production
        self.map: Map = map
        self.counter = Counter()
        self.unit_types = UnitTypes()
        self.upgrades = Upgrades(bot)
        self.special_locations = SpecialLocations(ramp=self.bot.main_base_ramp)
        self.changes_enacted: List[BuildOrderChange] = []

        for unit_type in BuildStarts.get_build_start(build_name):
            step = self.create_build_step(unit_type, None)
            self.static_queue.append(step)
        # self.build_a_worker: BuildStep = None
        # self.supply_build_step: BuildStep = None
        # self.queue_unit_type(UnitTypeId.BATTLECRUISER)

    async def update_references(self, units_by_tag: dict[int, Unit]) -> None:
        self.start_timer("update_references")
        for build_step in self.all_steps:
            build_step.update_references(units_by_tag)
            self.start_timer("draw_debug_box")
            build_step.draw_debug_box()
            self.stop_timer("draw_debug_box")
        await self.move_interupted_to_pending()
        self.stop_timer("update_references")

    @property
    def all_steps(self) -> List[BuildStep]:
        return self.started + self.interrupted_queue + self.priority_queue + self.static_queue + self.build_queue

    async def execute(self, army_ratio: float, rush_detected_type: RushType, enemy: Enemy):
        self.start_timer("build_order.execute")
        if rush_detected_type != RushType.NONE:
            self.rush_detected_type = rush_detected_type
        self.enact_rush_defense(self.rush_detected_type)
        if self.bot.time < 360 and (self.bot.enemy_units.filter(lambda u: u.type_id in (
                UnitTypeId.TEMPEST, UnitTypeId.BATTLECRUISER, UnitTypeId.CARRIER,
                UnitTypeId.WIDOWMINE, UnitTypeId.SWARMHOSTMP)) \
                    or self.map.natural_position and self.bot.enemy_units.closer_than(25, self.map.natural_position).amount >= 10):
            # abort static build order if we need a specialized response
            self.static_queue = self.static_queue[:10]

        self.build_queue.clear()

        only_build_units = False

        self.queue_townhall_work()
        self.queue_supply()
        self.queue_command_center()
        self.queue_upgrade()
        self.queue_marines(rush_detected_type)
        if len(self.static_queue) < 5 or self.bot.time > 300:
            self.queue_turret()

            # randomize unit queue so it doesn't get stuck on one unit type
            # XXX this should be better, maybe put one of the unit with least in current army, then one of next least, etc
            military_queue = self.get_military_queue(enemy)
            military_queue.sort(key=lambda step: random.randint(0,255), reverse=True)
            self.queue_prereqs(military_queue)
            self.add_to_build_queue(military_queue, queue=self.build_queue)

            only_build_units = self.bot.supply_left > 5 and army_ratio > 0.0 and army_ratio < 0.8
            if only_build_units:
                capacity_available = self.production.can_build_any(military_queue)
                if not capacity_available:
                    only_build_units = False
            self.queue_production(only_build_units)
            self.queue_medivacs()


        needed_resources: Cost = self.get_first_resource_shortage(only_build_units)

        self.start_timer("redistribute_workers")
        await self.workers.redistribute_workers(needed_resources)
        self.stop_timer("redistribute_workers")

        if len(self.static_queue) < 5 or self.bot.time > 300:
            self.queue_refinery()

        await self.execute_pending_builds(only_build_units)
        
        self.bot.client.debug_text_screen(self.get_build_queue_string(), (0.01, 0.1))
        self.stop_timer("build_order.execute")
    
    def get_build_queue_string(self):
        build_order_message = f"started={'\n'.join([step.friendly_name for step in self.started])}"
        build_order_message += f"\ninterrupted={'\n'.join([step.friendly_name for step in self.interrupted_queue])}"
        build_order_message += f"\npriority={'\n'.join([step.friendly_name for step in self.priority_queue])}"
        build_order_message += f"\nstatic={'\n'.join([step.friendly_name for step in self.static_queue])}"
        build_order_message += f"\nbuild_queue={'\n'.join([step.friendly_name for step in self.build_queue])}"
        build_order_message += f"\nunit_queue={'\n'.join([step.friendly_name for step in self.unit_queue])}"
        return build_order_message

    async def move_interupted_to_pending(self) -> None:
        self.start_timer("move_interupted_to_pending")
        to_promote: List[int] = []
        for idx, build_step in enumerate(self.started):
            if await build_step.is_interrupted():
                # move back to pending (demote)
                to_promote.append(idx)
        for idx in reversed(to_promote):
            step: BuildStep = self.started.pop(idx)
            step.interrupted_count += 1
            LogHelper.add_log(f"{step} interrupted")
            if isinstance(step, SCVBuildStep) and step.unit_being_built is None:
                if step.interrupted_count > 10:
                    LogHelper.add_log(f"{step} interrupted too many times, removing from build order")
                    continue
            if step.is_unit():
                self.build_queue.insert(0, step)
            else:
                self.interrupted_queue.insert(0, step)
        for structure in self.bot.structures_without_construction_SCVs:
            if structure.health_percentage > 0.05:
                for step in self.all_steps:
                    if not isinstance(step, SCVBuildStep):
                        continue
                    if step.unit_being_built and step.unit_being_built.tag == structure.tag:
                        break
                else:
                    # the build step got lost, re-add it
                    build_step = self.create_build_step(structure.type_id, structure)
                    self.interrupted_queue.insert(0, build_step)
        self.stop_timer("move_interupted_to_pending")

    def enact_rush_defense(self, rush_detected_type: RushType) -> None:
        if self.bot.time > 300 or self.bot.townhalls.amount > 2:
            # not a rush
            return
        if BuildOrderChange.BATTLECRUISER not in self.changes_enacted and rush_detected_type == RushType.BATTLECRUISER:
            self.changes_enacted.append(BuildOrderChange.BATTLECRUISER)
            self.add_to_build_queue([UnitTypeId.VIKINGFIGHTER] * 2, position=0, queue=self.priority_queue)
        if BuildOrderChange.REAPER not in self.changes_enacted and \
                self.bot.enemy_race == Race.Terran and self.bot.enemy_units(UnitTypeId.REAPER): # type: ignore
            self.changes_enacted.append(BuildOrderChange.REAPER)
            # queue one hellion in case of reaper rush
            self.add_to_build_queue([UnitTypeId.HELLION], position=0, queue=self.priority_queue)
            # swap reactor for techlab (faster, allows marauder)
            for step in self.static_queue:
                if step.is_unit_type(UnitTypeId.BARRACKSREACTOR):
                    self.static_queue.remove(step)
                    self.add_to_build_queue([UnitTypeId.BARRACKSTECHLAB, UnitTypeId.MARAUDER], position=0, queue=self.priority_queue)
                    break
        if BuildOrderChange.PROTOSS not in self.changes_enacted and self.bot.enemy_race == Race.Protoss: # type: ignore
            self.changes_enacted.append(BuildOrderChange.PROTOSS)
            self.move_between_queues(UnitTypeId.SUPPLYDEPOT, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.REFINERY, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.BARRACKS, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.REFINERY, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.REAPER, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.SUPPLYDEPOT, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.COMMANDCENTER, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.FACTORY, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.BARRACKSREACTOR, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.STARPORT, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.STARPORTTECHLAB, self.static_queue, self.priority_queue)
            self.add_to_build_queue([UnitTypeId.BANSHEE, UpgradeId.BANSHEECLOAK], queue=self.priority_queue)
            self.add_to_build_queue([UnitTypeId.BANSHEE], queue=self.static_queue, position=5, add_prereqs=False)
        if BuildOrderChange.RUSH not in self.changes_enacted and rush_detected_type not in (RushType.BATTLECRUISER, RushType.NONE):
            self.changes_enacted.append(BuildOrderChange.RUSH)
            # prioritize bunker and first tank
            self.move_between_queues(UnitTypeId.REAPER, self.static_queue, self.priority_queue)
            if rush_detected_type == RushType.PROXY:
                if self.bot.structures([UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED]).amount < 2:
                    # make sure to build second depot before bunker
                    self.move_between_queues(UnitTypeId.SUPPLYDEPOT, self.static_queue, self.priority_queue)
                # proxy will hit earlier, really need bunker
                if self.move_between_queues(UnitTypeId.BUNKER, self.static_queue, self.priority_queue):
                    # add a second bunker for low ground
                    self.add_to_build_queue([UnitTypeId.BUNKER], queue=self.static_queue, position=10)
            self.move_between_queues(UnitTypeId.MARINE, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.BARRACKSREACTOR, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.FACTORY, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.FACTORYTECHLAB, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.SIEGETANK, self.static_queue, self.priority_queue)
            if rush_detected_type == RushType.STANDARD:
                if self.bot.structures([UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED]).amount < 2:
                    # make sure to build second depot before bunker
                    self.move_between_queues(UnitTypeId.SUPPLYDEPOT, self.static_queue, self.priority_queue)
                if self.move_between_queues(UnitTypeId.BUNKER, self.static_queue, self.priority_queue):
                    # add a second bunker for low ground
                    self.add_to_build_queue([UnitTypeId.BUNKER], queue=self.static_queue, position=10)
    
    def move_between_queues(self, unit_type: UnitTypeId, from_queue: List[BuildStep], to_queue: List[BuildStep]) -> bool:
        for step in from_queue:
            if step.is_unit_type(unit_type):
                from_queue.remove(step)
                to_queue.append(step)
                return True
        return False

    def add_to_build_queue(self, unit_types: List[UnitTypeId | UpgradeId],
                           position: int | None = None, queue: List[BuildStep] | None = None, add_prereqs: bool = True) -> None:
        if queue is None:
            queue = self.build_queue
        all_prereqs: List[UnitTypeId | UpgradeId] = []
        if add_prereqs:
            for unit_type in unit_types:
                if isinstance(unit_type, UpgradeId):
                    continue
                prereqs = self.production.build_order_with_prereqs(unit_type)
                for prereq in prereqs:
                    if prereq != unit_type and prereq not in all_prereqs:
                        all_prereqs.append(prereq)
            unit_types = all_prereqs + unit_types
                
        for build_step in queue:
            if isinstance(build_step, StructureBuildStep) or isinstance(build_step, SCVBuildStep):
                if build_step.unit_type_id in unit_types:
                    unit_types.remove(build_step.unit_type_id)
                    if not unit_types:
                        break
            elif isinstance(build_step, UpgradeBuildStep):
                if build_step.upgrade_id in unit_types:
                    unit_types.remove(build_step.upgrade_id)
                    if not unit_types:
                        break
        steps_to_add: List[BuildStep] = [self.create_build_step(unit_type) for unit_type in unit_types]
        if steps_to_add:
            if position is not None:
                steps_to_add = queue[:position] + steps_to_add + queue[position:]
                queue.clear()
            queue.extend(steps_to_add)

    def create_build_step(self, unit_type: UnitTypeId | UpgradeId, existing_structure: Unit | None = None) -> BuildStep:
        if isinstance(unit_type, UpgradeId):
            return UpgradeBuildStep(unit_type, self.bot, self.workers, self.production, self.map)
        if UnitTypeId.SCV in self.production.get_builder_type(unit_type):
            build_step = SCVBuildStep(unit_type, self.bot, self.workers, self.production, self.map)
            if existing_structure:
                build_step.unit_being_built = existing_structure
            return build_step
        return StructureBuildStep(unit_type, self.bot, self.workers, self.production, self.map)
    
    def queue_prereqs(self, unit_types: List[UnitTypeId | UpgradeId]) -> None:
        for unit_type in unit_types:
            prereqs = self.production.build_order_with_prereqs(unit_type)
            prereqs.remove(unit_type)
            if prereqs:
                self.add_to_build_queue(prereqs, queue=self.build_queue)

    def get_military_queue(self, enemy: Enemy) -> List[UnitTypeId | UpgradeId]:
        self.start_timer("get_military_queue")
        worker_supply_cap = min(self.workers.max_workers, self.bot.workers.amount * 1.15)
        military_cap = self.bot.supply_cap - worker_supply_cap
        ideal_composition = self.counter.get_counters(enemy.get_army(include_scouts=True, seconds_since_killed=180))
        current_composition = UnitTypes.count_units_by_type(self.bot.units)
        if not ideal_composition:
            # if no enemy units, current army is doing pretty well?
            for unit_type, count in current_composition.items():
                ideal_composition[unit_type] = count
        ideal_supply = 0
        for unit_type, count in ideal_composition.items():
            if unit_type in (UnitTypeId.MULE, UnitTypeId.SCV):
                continue
            supply_cost: int = self.unit_types.get_unit_info(unit_type)["supply"]
            ideal_supply += supply_cost * count
        # scale composition to fit military cap
        buildable_percentage = min(1.0, military_cap / ideal_supply) if ideal_supply > 0 else 0
        queue: List[UnitTypeId | UpgradeId] = []
        if UnitTypeId.RAVEN not in ideal_composition:
            # have at least one raven for detection
            ideal_composition[UnitTypeId.RAVEN] = 0.1
        if UnitTypeId.VIKINGFIGHTER not in ideal_composition:
            # have at least one viking for scouting
            ideal_composition[UnitTypeId.VIKINGFIGHTER] = 0.1
        queued_supply = 0

        while queued_supply < self.bot.supply_left and len(queue) < 10:
            for unit_type, count in ideal_composition.items():
                if unit_type in (UnitTypeId.MULE, UnitTypeId.SCV):
                    continue
                ideal_count = math.ceil(count * buildable_percentage)
                existing_count = current_composition.get(unit_type, 0)
                in_progress_count = self.get_in_progress_count(unit_type)

                queue_count = ideal_count - existing_count - in_progress_count
                if queue_count > 0:
                    queued_supply += queue_count * self.unit_types.get_unit_info(unit_type)["supply"]
                    queue.extend([unit_type] * queue_count)
            buildable_percentage += 0.5
        self.stop_timer("get_military_queue")
        return queue

    def queue_townhall_work(self) -> None:
        self.start_timer("queue_townhall_build")
        if len(self.bot.townhalls) == 1 and self.bot.workers.amount >= 18 or self.bot.time < 15:
            # pause workers to save for first expansion
            self.stop_timer("queue_townhall_build")
            return

        available_townhalls = self.bot.townhalls.filter(lambda cc: cc.is_ready and cc.is_idle and not cc.is_flying)
        worker_build_capacity: int = len(available_townhalls)
        available_command_centers = available_townhalls.filter(lambda cc: cc.type_id == UnitTypeId.COMMANDCENTER)
        if available_command_centers:
            if len(self.bot.townhalls.of_type(UnitTypeId.ORBITALCOMMAND)) < 3 and self.bot.time > 90 \
                    and self.get_in_progress_count(UnitTypeId.ORBITALCOMMAND) == 0:
                # if self.bot.minerals >= 150 and self.bot.structures(UnitTypeId.BARRACKS).ready:
                # queue orbital instead if can afford
                self.add_to_build_queue([UnitTypeId.ORBITALCOMMAND], queue=self.priority_queue, position=0)
                self.stop_timer("queue_townhall_build")
                return
            elif self.bot.minerals >= 150 and self.bot.vespene >= 150 and self.bot.structures(UnitTypeId.ENGINEERINGBAY).ready:
                self.add_to_build_queue([UnitTypeId.PLANETARYFORTRESS], queue=self.priority_queue, position=0)
                self.stop_timer("queue_townhall_build")
                return

        desired_worker_count = self.workers.max_workers
        number_to_build = desired_worker_count - len(self.workers.assignments_by_worker)
        if (
            worker_build_capacity > 0
            and number_to_build > 0
        ):
            self.add_to_build_queue([UnitTypeId.SCV] * min(number_to_build, worker_build_capacity), queue=self.priority_queue, position=0)
        self.stop_timer("queue_townhall_build")

    def queue_supply(self) -> None:
        self.start_timer("queue_supply")
        in_static_queue = self.get_queued_count(UnitTypeId.SUPPLYDEPOT) > 0
        if 0 < self.bot.supply_cap < 200 and not in_static_queue:
            in_progress_count = self.get_in_progress_count(UnitTypeId.SUPPLYDEPOT)
            supply_percent_remaining = self.bot.supply_left / self.bot.supply_cap
            if self.bot.supply_left < 10 or supply_percent_remaining <= 0.2:
                needed_count = 1
                # queue another if supply is very low
                if (self.bot.supply_left < 2 or supply_percent_remaining <= 0.1):
                    needed_count += 1
                if in_progress_count < needed_count:
                    self.add_to_build_queue([UnitTypeId.SUPPLYDEPOT] * (needed_count - in_progress_count), queue=self.priority_queue)
        self.stop_timer("queue_supply")

    def get_in_progress_count(self, unit_type: UnitTypeId | UpgradeId) -> int:
        count = 0
        for build_step in self.started + self.interrupted_queue:
            if build_step.is_unit_type(unit_type):
                count += 1
        return count

    def get_queued_count(self, unit_type: UnitTypeId, queue: List[BuildStep] | None = None) -> int:
        if queue is None:
            queue = self.priority_queue + self.static_queue + self.build_queue
        count = 0
        for build_step in queue:
            if build_step.is_unit_type(unit_type):
                count += 1
        return count

    def queue_command_center(self) -> None:
        self.start_timer("queue_command_center")
        if self.bot.townhalls.amount == 2 and self.bot.townhalls.flying:
            # don't queue another expansion if current one is still in air
            # probably unsafe or it would have landed
            self.stop_timer("queue_command_center")
            return
        if self.bot.time < 100 or self.rush_detected_type != RushType.NONE and self.bot.time < 300:
            # don't expand too early during rush
            self.stop_timer("queue_command_center")
            return

        projected_worker_capacity = self.workers.get_mineral_capacity()
        cc_count = self.get_queued_count(UnitTypeId.COMMANDCENTER, self.all_steps)
        projected_worker_capacity += cc_count * 16

        # adds number of townhalls to account for near-term production
        projected_worker_count = min(self.workers.max_workers, len(self.workers.assignments_by_job[WorkerJobType.MINERALS]) + len(self.bot.townhalls.ready) * 4)
        surplus_worker_count = projected_worker_count - projected_worker_capacity
        
        cc_count = self.get_in_progress_count(UnitTypeId.COMMANDCENTER) + self.get_queued_count(UnitTypeId.COMMANDCENTER)
        needed_cc_count = math.ceil(surplus_worker_count / 16)

        # expand if running out of room for workers at current bases
        if needed_cc_count > cc_count:
            self.add_to_build_queue([UnitTypeId.COMMANDCENTER] * (needed_cc_count - cc_count), queue=self.priority_queue)
        self.stop_timer("queue_command_center")

    def queue_refinery(self) -> None:
        self.start_timer("queue_refinery")
        refinery_count = len(self.bot.gas_buildings.ready) + self.get_in_progress_count(UnitTypeId.REFINERY) + self.get_queued_count(UnitTypeId.REFINERY)
        # build refinery if less than 2 per town hall (function is only called if gas is needed but no room to move workers)
        if self.bot.townhalls.ready:
            geysirs = self.bot.vespene_geyser.in_distance_of_group(
                distance=10, other_units=self.bot.townhalls.ready
            )
            if refinery_count < len(geysirs):
                self.add_to_build_queue([UnitTypeId.REFINERY], queue=self.priority_queue)
        # should also build a new one if current bases run out of resources
        self.stop_timer("queue_refinery")

    def queue_production(self, only_build_units: bool):
        self.start_timer("queue_production")
        # add more barracks/factories/starports to handle backlog of pending affordable units
        self.start_timer("queue_production-get_affordable_build_list")
        affordable_units: List[UnitTypeId] = self.get_affordable_build_list(only_build_units)
        if len(affordable_units) == 0 and len(self.static_queue) < 4 and self.unit_queue:
            if isinstance(self.unit_queue[0], SCVBuildStep) or isinstance(self.unit_queue[0], StructureBuildStep):
                affordable_units.append(self.unit_queue[0].unit_type_id)
        self.stop_timer("queue_production-get_affordable_build_list")
        self.start_timer("queue_production-additional_needed_production")
        extra_production: List[UnitTypeId | UpgradeId] = self.production.additional_needed_production(affordable_units)
        # only add if not already in progress
        extra_production = self.remove_in_progress_from_list(extra_production)
        self.stop_timer("queue_production-additional_needed_production")
        self.start_timer("queue_production-add_to_build_order")
        self.add_to_build_queue(extra_production, position=0, queue=self.static_queue)
        self.stop_timer("queue_production-add_to_build_order")
        self.stop_timer("queue_production")

    def queue_marines(self, rush_detected_type: RushType) -> None:
        self.start_timer("queue_marines")
        # use excess minerals and idle barracks
        need_early_marines: bool = self.bot.time < 300 and \
            (rush_detected_type != RushType.NONE or self.bot.enemy_units.closer_than(20, self.map.natural_position).amount > 2)
        if need_early_marines and self.bot.minerals >= 50:
            idle_capacity = self.production.get_build_capacity(UnitTypeId.BARRACKS)
            priority_queue_count = self.get_queued_count(UnitTypeId.MARINE, self.priority_queue)
            if idle_capacity > 0 and priority_queue_count == 0:
                if not self.move_between_queues(UnitTypeId.MARINE, self.static_queue, self.priority_queue):
                    self.add_to_build_queue([UnitTypeId.MARINE], queue=self.priority_queue)
        elif self.bot.minerals > 500 and self.bot.supply_left > 15:
            idle_capacity = self.production.get_build_capacity(UnitTypeId.BARRACKS)
            if idle_capacity > 0:
                self.add_to_build_queue([UnitTypeId.MARINE] * idle_capacity, queue=self.static_queue)
            elif self.get_in_progress_count(UnitTypeId.BARRACKS) + self.get_in_progress_count(UnitTypeId.BARRACKSREACTOR) < 3:
                self.add_to_build_queue([UnitTypeId.BARRACKS, UnitTypeId.BARRACKSREACTOR], queue=self.static_queue)
        self.stop_timer("queue_marines")

    def queue_medivacs(self) -> None:
        self.start_timer("queue_medivacs")
        marine_count = self.bot.units.of_type({UnitTypeId.MARINE}).amount
        marauder_count = self.bot.units.of_type({UnitTypeId.MARAUDER}).amount
        medivac_count = self.bot.units.of_type(UnitTypeId.MEDIVAC).amount + self.get_in_progress_count(UnitTypeId.MEDIVAC)
        desired_medivac_count = min(6, marine_count // 8 + marauder_count // 4)
        queue_count = desired_medivac_count - medivac_count
        # use excess minerals and idle starports
        if queue_count > 0:
            self.add_to_build_queue([UnitTypeId.MEDIVAC] * queue_count, queue=self.static_queue)
        self.stop_timer("queue_medivacs")

    def remove_in_progress_from_list(self, build_list: List[UnitTypeId | UpgradeId]) -> List[UnitTypeId | UpgradeId]:
        in_progress_counts: Dict[UnitTypeId | UpgradeId, int] = {}
        result: List[UnitTypeId | UpgradeId] = []
        for unit_type in build_list:
            if unit_type not in in_progress_counts:
                in_progress_counts[unit_type] = self.get_in_progress_count(unit_type)
            if in_progress_counts[unit_type] > 0:
                in_progress_counts[unit_type] -= 1
            else:
                result.append(unit_type)
        return result

    upgrade_building_types = {
        UnitTypeId.ARMORY,
        # UnitTypeId.FUSIONCORE,
        UnitTypeId.ENGINEERINGBAY,
        UnitTypeId.BARRACKSTECHLAB,
        UnitTypeId.FACTORYTECHLAB,
        UnitTypeId.STARPORTTECHLAB,
        # UnitTypeId.GHOSTACADEMY,
    }
    max_facilities: Dict[UnitTypeId, int] = {
        UnitTypeId.ARMORY: 3,
        UnitTypeId.ENGINEERINGBAY: 2,
        UnitTypeId.BARRACKSTECHLAB: 2,
        UnitTypeId.FACTORYTECHLAB: 2,
        UnitTypeId.STARPORTTECHLAB: 2,
        # UnitTypeId.GHOSTACADEMY: 1,
        # UnitTypeId.FUSIONCORE: 1,
    }

    def queue_upgrade(self) -> None:
        self.start_timer("queue_upgrade")
        for facility_type in self.upgrade_building_types:
            next_upgrade = self.upgrades.next_upgrade(facility_type)
            if next_upgrade is None or self.upgrade_is_in_progress(next_upgrade):
                continue
            if self.bot.structures(facility_type).ready.idle:
                self.add_to_build_queue([next_upgrade], queue=self.priority_queue)
            elif self.bot.townhalls.amount > 2 and self.get_in_progress_count(facility_type) == 0:
                facilities = self.bot.structures(facility_type)
                if not facilities or self.bot.minerals > 500 and self.bot.vespene > 250 \
                        and len(facilities) < self.max_facilities.get(facility_type, 1):
                    new_build_steps = []
                    if facility_type in self.production.add_on_types:
                        # add facility with no addon if needed
                        builder_type = self.production.get_cheapest_builder_type(facility_type)
                        no_addon_count = len(self.production.facilities[builder_type][UnitTypeId.NOTAUNIT])
                        in_progress_builder_count = self.get_in_progress_count(builder_type)
                        if in_progress_builder_count == 0 and no_addon_count == 0:
                            new_build_steps = self.production.build_order_with_prereqs(builder_type)
                        new_build_steps.append(facility_type)
                    else:
                        queued_count = self.get_queued_count(facility_type)
                        if queued_count == 0:
                            # build if none or if we have excess resources
                            new_build_steps = self.production.build_order_with_prereqs(facility_type)
                            new_build_steps = self.remove_in_progress_from_list(new_build_steps)
                    self.add_to_build_queue(new_build_steps, queue=self.priority_queue, position=0)
        self.stop_timer("queue_upgrade")

    def upgrade_is_in_progress(self, upgrade_type: UpgradeId) -> bool:
        for build_step in self.started:
            if build_step.is_upgrade_type(upgrade_type):
                return True
        return False

    def queue_planetary(self) -> None:
        self.start_timer("queue_planetary")
        planetary_count = len(self.bot.structures.of_type(UnitTypeId.PLANETARYFORTRESS)) + self.get_in_progress_count(UnitTypeId.PLANETARYFORTRESS)
        cc_count = len(self.bot.structures.of_type(UnitTypeId.COMMANDCENTER))
        if self.bot.time > 500 and planetary_count < cc_count:
            self.add_to_build_queue(self.production.build_order_with_prereqs(UnitTypeId.PLANETARYFORTRESS))
        self.stop_timer("queue_planetary")

    def queue_turret(self) -> None:
        self.start_timer("queue_turret")
        if self.bot.time > 300:
            turrets = self.bot.structures.of_type(UnitTypeId.MISSILETURRET)
            turret_count = len(turrets.ready)
            construction_started_count = len(turrets) - turret_count
            in_progress_count = self.get_in_progress_count(UnitTypeId.MISSILETURRET)
            construction_pending_count = in_progress_count - construction_started_count
            if construction_pending_count > 0:
                # don't queue another until this starts to avoid building two at same base
                self.stop_timer("queue_turret")
                return
            base_count = len(self.bot.structures.of_type({UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS}))
            if turret_count + in_progress_count < base_count:
                self.add_to_build_queue(self.production.build_order_with_prereqs(UnitTypeId.MISSILETURRET))
            elif in_progress_count == 0:
                # add turrets to bases without one in case multiple were built at a different base
                for townhall in self.bot.townhalls:
                    for turret in turrets:
                        if turret.distance_to_squared(townhall) < 100:
                            break
                    else:
                        self.add_to_build_queue(self.production.build_order_with_prereqs(UnitTypeId.MISSILETURRET))

        self.stop_timer("queue_turret")

    def get_first_resource_shortage(self, only_build_units: bool) -> Cost:
        self.start_timer("get_first_resource_shortage")
        needed_resources: Cost = Cost(-self.bot.minerals, -self.bot.vespene)
        # find first shortage
        if self.priority_queue and needed_resources.minerals <= 0 and needed_resources.vespene <= 0:
            needed_resources = self.count_resources_in_queue(self.priority_queue, only_build_units, needed_resources)
        if self.static_queue and needed_resources.minerals <= 0 and needed_resources.vespene <= 0:
            needed_resources = self.count_resources_in_queue(self.static_queue, only_build_units, needed_resources)
        if self.build_queue and needed_resources.minerals <= 0 and needed_resources.vespene <= 0:
            needed_resources = self.count_resources_in_queue(self.build_queue, only_build_units, needed_resources)
        self.stop_timer("get_first_resource_shortage")
        return needed_resources
    
    def count_resources_in_queue(self, build_queue: List[BuildStep], only_build_units: bool, needed_resources: Cost) -> Cost:
        for build_step in build_queue:
            if needed_resources.minerals > 0 or needed_resources.vespene > 0:
                break
            if only_build_units and UnitTypeId.SCV in build_step.builder_type:
                continue
            needed_resources.minerals += build_step.cost.minerals
            needed_resources.vespene += build_step.cost.vespene
        return needed_resources

    def get_affordable_build_list(self, only_build_units: bool) -> List[UnitTypeId]:
        affordable_items: List[UnitTypeId] = []
        needed_resources: Cost = Cost(-self.bot.minerals, -self.bot.vespene)

        # find first shortage, unit_queue hasn't been added to build_queue yet
        for build_step in self.priority_queue + self.static_queue + self.build_queue + self.unit_queue:
            if only_build_units and not build_step.is_unit():
                continue
            if not self.subtract_and_can_afford(needed_resources, build_step.cost):
                break
            unit_type_id = build_step.get_unit_type_id()
            if unit_type_id:
                affordable_items.append(unit_type_id)
        return affordable_items

    def subtract_and_can_afford(self, needed_resources: Cost, step_cost: Cost) -> bool:
        needed_resources.minerals += step_cost.minerals
        needed_resources.vespene += step_cost.vespene
        return needed_resources.minerals <= 0 and needed_resources.vespene <= 0

    def update_completed_unit(self, completed_unit: Unit) -> None:
        for idx, in_progress_step in enumerate(self.started):
            if in_progress_step.is_unit_type(completed_unit.type_id):
                if completed_unit.is_structure:
                    if in_progress_step.manhattan_distance(completed_unit.position) > 2:
                        # not the same building
                        continue
                if in_progress_step.unit_in_charge:
                    if in_progress_step.unit_in_charge.type_id == UnitTypeId.SCV:
                        self.workers.set_as_idle(in_progress_step.unit_in_charge)
                else:
                    # not sure if/how we get here
                    continue
                in_progress_step.completed_time = self.bot.time
                self.move_to_complete(self.started.pop(idx))
                break

    def move_to_complete(self, build_step: BuildStep) -> None:
        self.complete.append(build_step)
        for timer_name in build_step.timers.keys():
            if timer_name not in self.timers:
                self.timers[timer_name] = build_step.timers[timer_name]
            else:
                self.timers[timer_name]['total'] += build_step.timers[timer_name]['total']

    def update_started_structure(self, started_structure: Unit) -> None:
        for in_progress_step in self.started:
            # skip upgrades and steps that already have a structure assigned
            if isinstance(in_progress_step, UpgradeId) or in_progress_step.get_structure_being_built():
                continue
            if in_progress_step.is_unit_type(started_structure.type_id):
                if in_progress_step.unit_in_charge and in_progress_step.unit_in_charge.type_id == UnitTypeId.SCV:
                    try:
                        in_progress_step.unit_in_charge = self.get_updated_unit_reference(in_progress_step.unit_in_charge, self.bot)
                    except self.UnitNotFound:
                        continue
                    if not in_progress_step.unit_in_charge.is_constructing_scv:
                        # wrong worker
                        continue
                    self.workers.update_assigment(in_progress_step.unit_in_charge, WorkerJobType.BUILD, started_structure)
                in_progress_step.set_unit_being_built(started_structure)
                break
        # see if this is a ramp blocker
        ramp_blocker: SpecialLocation
        for ramp_blocker in self.special_locations.ramp_blockers:
            if ramp_blocker == started_structure:
                ramp_blocker.unit_tag = started_structure.tag
                ramp_blocker.is_started = True

    def update_completed_structure(self, completed_structure: Unit) -> None:
        if completed_structure.type_id == UnitTypeId.AUTOTURRET:
            return

        for idx, in_progress_step in enumerate(self.started):
            if in_progress_step.is_same_structure(completed_structure):
                builder = in_progress_step.unit_in_charge
                in_progress_step.completed_time = self.bot.time
                if builder and builder.type_id == UnitTypeId.SCV:
                    if in_progress_step.is_unit_type(UnitTypeId.REFINERY):
                        self.workers.vespene.add_node(completed_structure)
                        self.workers.update_assigment(builder, WorkerJobType.VESPENE, completed_structure)
                    else:
                        self.workers.set_as_idle(builder)
                self.move_to_complete(self.started.pop(idx))
                break
        ramp_blocker: SpecialLocation
        for ramp_blocker in self.special_locations.ramp_blockers:
            if ramp_blocker == completed_structure:
                ramp_blocker.unit_tag = completed_structure.tag
                ramp_blocker.is_complete = True

    def update_completed_upgrade(self, upgrade: UpgradeId):
        for idx, in_progress_step in enumerate(self.started):
            if in_progress_step.is_upgrade_type(upgrade):
                self.move_to_complete(self.started.pop(idx))
                break

    def cancel_damaged_structure(self, unit: Unit, total_damage_amount: float):
        if unit.health_percentage > 0.05:
            return
        for idx, build_step in enumerate(self.all_steps):
            if build_step.is_same_structure(unit):
                build_step.cancel_construction()
                if build_step.is_unit_type(UnitTypeId.COMMANDCENTER) and len(self.bot.townhalls.ready) == 1:
                    self.rush_detected_type = RushType.STANDARD
                break

    async def execute_pending_builds(self, only_build_units: bool) -> None:
        self.start_timer("execute_pending_builds")
        allow_skip = self.bot.time > 60
        remaining_resources: Cost = await self.build_from_queue(self.interrupted_queue, only_build_units, self.rush_detected_type, allow_skip)
        if remaining_resources.minerals > 0:
            remaining_resources: Cost = await self.build_from_queue(self.priority_queue, only_build_units, self.rush_detected_type, allow_skip, remaining_resources)
        if remaining_resources.minerals > 0:
            remaining_resources = await self.build_from_queue(self.static_queue, only_build_units, self.rush_detected_type, True, remaining_resources)
        if remaining_resources.minerals > 0:
            await self.build_from_queue(self.build_queue, only_build_units, self.rush_detected_type, True, remaining_resources)
        self.stop_timer("execute_pending_builds")

    async def build_from_queue(self, build_queue: List[BuildStep], only_build_units: bool, rush_detected_type: RushType,
                               allow_skip: bool = True, remaining_resources: Cost | None = None) -> Cost:
        build_response = BuildResponseCode.QUEUE_EMPTY
        execution_index = -1
        failed_types: List[UnitTypeId] = []
        if remaining_resources is None:
            remaining_resources = Cost(self.bot.minerals, self.bot.vespene)

        while execution_index < len(build_queue):
            execution_index += 1
            try:
                build_step = build_queue[execution_index]
            except IndexError:
                break
            # skip steps for various reasons
            if build_step.get_unit_type_id() in failed_types:
                continue
            if self.bot.supply_left < build_step.supply_cost and build_step.supply_cost > 0:
                build_response = BuildResponseCode.NO_SUPPLY
                continue
            if only_build_units and not build_step.is_unit() and not build_step.is_unit_type(UnitTypeId.COMMANDCENTER):
                continue
            time_since_last_cancel = self.bot.time - build_step.last_cancel_time
            if time_since_last_cancel < 10:
                continue

            percent_affordable = 1.0
            if not build_step.is_in_progress:
                percent_affordable = self.percent_affordable(remaining_resources, build_step.cost)
                if remaining_resources.minerals < 0:
                    break
                remaining_resources = remaining_resources - build_step.cost
            if percent_affordable < 1.0:
                build_response = BuildResponseCode.NO_RESOURCES
                if percent_affordable >= 0.75 and isinstance(build_step, SCVBuildStep) \
                        and self.bot.tech_requirement_progress(build_step.unit_type_id) == 1.0:
                    await build_step.position_worker(self.special_locations, rush_detected_type)
                continue

            # XXX slightly slow
            self.start_timer("build_step.execute")
            build_response = await build_step.execute(self.special_locations, rush_detected_type)
            self.stop_timer("build_step.execute")
            self.start_timer(f"handle response {build_response}")
            if build_response == BuildResponseCode.SUCCESS:
                LogHelper.add_log(f"Started building {build_step}")
                self.started.append(build_queue.pop(execution_index))
                if build_step.interrupted_count > 5:
                    # can't trust that this actually got built
                    continue
                remaining_resources.minerals = 0
                break
            else:
                if build_response != BuildResponseCode.NO_FACILITY:
                    LogHelper.add_log(f"failed to start {build_step}: {build_response}")
                if not allow_skip:
                    remaining_resources.minerals = 0
                    break
                if self.bot.time > 60:
                    remaining_resources = remaining_resources + build_step.cost
                if build_response == BuildResponseCode.NO_LOCATION:
                    continue
                unit_type = build_step.get_unit_type_id()
                if unit_type:
                    failed_types.append(unit_type)
                if build_response == BuildResponseCode.NO_FACILITY:
                    if unit_type in self.production.add_on_types:
                        # unqueue addons that don't have a parent factory/barracks/starport
                        builder_type = self.production.get_cheapest_builder_type(unit_type)
                        no_addon_count = len(self.production.facilities[builder_type][UnitTypeId.NOTAUNIT])
                        in_progress_builder_count = self.get_in_progress_count(builder_type)
                        earlier_in_queue = max([step.get_unit_type_id() == builder_type for step in build_queue[:execution_index]], default=False)
                        if in_progress_builder_count == 0 and no_addon_count == 0 and not earlier_in_queue:
                            build_queue.pop(execution_index)
                            remaining_resources.minerals = 0
                            return remaining_resources
            self.stop_timer(f"handle response {build_response}")
        self.stop_timer("execute_pending_builds")
        return remaining_resources

    def can_afford(self, remaining_resources: Cost, requested_cost: Cost) -> bool:
        return (
            requested_cost.minerals <= remaining_resources.minerals
            and requested_cost.vespene <= remaining_resources.vespene
        )
    
    def get_blueprints(self) -> List[BuildStep]:
        return [step for step in self.started if step.has_position_reserved()]
    
    def get_assigned_worker_tags(self) -> List[int]:
        return [
            step.unit_in_charge.tag for step in self.all_steps
            if UnitTypeId.SCV in step.builder_type and step.unit_in_charge is not None
        ]
    
    def percent_affordable(self, remaining_resources: Cost, requested_cost: Cost) -> float:
        mineral_percent = 1.0
        vespene_percent = 1.0
        if requested_cost.minerals > 0:
            mineral_percent = remaining_resources.minerals / requested_cost.minerals
        if requested_cost.vespene > 0:
            vespene_percent = remaining_resources.vespene / requested_cost.vespene
        return min(mineral_percent, vespene_percent)
