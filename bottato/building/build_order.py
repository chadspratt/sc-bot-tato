import math
import random
from typing import Dict, List, Set, Tuple

from cython_extensions.geometry import cy_distance_to, cy_towards
from cython_extensions.units_utils import cy_closer_than, cy_closest_to
from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.game_data import Cost
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.building.build_starts import BuildStarts
from bottato.building.build_step import BuildStep
from bottato.building.scv_build_step import SCVBuildStep
from bottato.building.special_locations import SpecialLocation, SpecialLocations
from bottato.building.structure_build_step import StructureBuildStep
from bottato.building.upgrade_build_step import UpgradeBuildStep
from bottato.counter import Counter
from bottato.economy.production import Production
from bottato.economy.workers import Workers
from bottato.enemy import Enemy
from bottato.enums import (
    BuildOrderChange,
    BuildResponseCode,
    BuildType,
    Tactic,
    WorkerJobType,
)
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.military import Military
from bottato.mixins import timed, timed_async
from bottato.squad.enemy_intel import EnemyIntel
from bottato.tactics import Tactics
from bottato.tech_tree import TECH_TREE
from bottato.unit_reference_helper import UnitReferenceHelper
from bottato.unit_types import UnitTypes
from bottato.upgrades import Upgrades


class BuildOrder():
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
    time_to_deviate_from_build_order = 50

    def __init__(self, build_name: str, bot: BotAI, tactics: Tactics, workers: Workers, production: Production) -> None:
        self.bot = bot
        self.workers = workers
        self.production = production
        self.tactics = tactics
        self.map = tactics.map
        self.intel = tactics.intel
        self.enemy = tactics.enemy

        self.counter = Counter()
        self.unit_types = UnitTypes()
        self.upgrades = Upgrades(bot)
        self.special_locations = SpecialLocations(ramp=self.bot.main_base_ramp)
        self.changes_enacted: Set[BuildOrderChange] = set()
        self.only_build_units: bool = False
        self.floating_building_destinations: Dict[int, Point2] = {}

        if self.bot.enemy_race == Race.Protoss:
            build_name += " protoss"
        elif self.bot.enemy_race == Race.Zerg:
            build_name += " zerg"
        for unit_type in BuildStarts.get_build_start(build_name):
            step = self.create_build_step(unit_type, None)
            self.static_queue.append(step)

    @timed_async
    async def update_references(self) -> None:
        for build_step in self.all_steps:
            build_step.update_references()
            build_step.draw_debug_box()
        await self.move_interupted_to_pending()

    @property
    def all_steps(self) -> List[BuildStep]:
        return self.started + self.interrupted_queue + self.priority_queue + self.static_queue + self.build_queue

    @timed_async
    async def execute(self, floating_building_destinations: Dict[int, Point2]) -> Cost:
        self.floating_building_destinations = floating_building_destinations
        detected_enemy_builds = self.intel.enemy_builds_detected
        self.enact_build_changes(detected_enemy_builds)
        if self.bot.time < 360 and (self.bot.enemy_units.filter(lambda u: u.type_id in (
                UnitTypeId.TEMPEST, UnitTypeId.BATTLECRUISER, UnitTypeId.CARRIER,
                UnitTypeId.WIDOWMINE, UnitTypeId.SWARMHOSTMP)) \
                    or self.map.natural_position and len(cy_closer_than(self.bot.enemy_units, 25, self.map.natural_position)) >= 10):
            # abort static build order if we need a specialized response
            self.static_queue = self.static_queue[:10]

        self.build_queue.clear()

        self.only_build_units = False

        self.queue_townhall_work(detected_enemy_builds)
        self.queue_supply()
        self.queue_command_center(self.intel.army_ratio, detected_enemy_builds)
        self.queue_upgrade(self.changes_enacted)
        self.queue_marines(detected_enemy_builds, self.intel.army_ratio)
        if len(self.static_queue) < 5 or self.bot.time > 300:
            self.queue_turret(self.intel)
            await self.queue_bunker(self.intel.main_army_staging_location)

            # randomize unit queue so it doesn't get stuck on one unit type
            military_queue, priority_military_queue = self.get_military_queue(self.enemy, self.intel)
            military_queue.sort(key=lambda step: random.randint(0,255))
            # prioritize building at least one of each requested unit type
            military_queue.sort(key=lambda step: isinstance(step, UnitTypeId) and self.bot.units(step).amount > 0)
            self.queue_prereqs(military_queue)
            self.add_to_build_queue(priority_military_queue, queue=self.build_queue)
            self.add_to_build_queue(military_queue, queue=self.build_queue)

            self.only_build_units = self.bot.supply_left > 6 and 0.0 < self.intel.army_ratio < 0.6
            if self.only_build_units:
                capacity_available = self.production.can_build_any(military_queue)
                if not capacity_available:
                    self.queue_production(only_build_units = True)
            else:
                self.queue_production(only_build_units = False)
            self.queue_medivacs()

        if len(self.static_queue) < 5 or self.bot.time > 300:
            self.queue_refinery()

        remaining_resources: Cost = await self.execute_pending_builds(self.only_build_units, detected_enemy_builds)
        
        self.bot.client.debug_text_screen(self.get_build_queue_string(), (0.01, 0.1))
        return remaining_resources
    
    def get_build_queue_string(self):
        build_order_message = f"only_build_units={self.only_build_units}"
        build_order_message += f"\nstarted={'\n'.join([step.friendly_name for step in self.started])}"
        build_order_message += f"\ninterrupted={'\n'.join([step.friendly_name for step in self.interrupted_queue])}"
        build_order_message += f"\npriority={'\n'.join([step.friendly_name for step in self.priority_queue])}"
        build_order_message += f"\nstatic={'\n'.join([step.friendly_name for step in self.static_queue])}"
        build_order_message += f"\nbuild_queue={'\n'.join([step.friendly_name for step in self.build_queue])}"
        build_order_message += f"\nunit_queue={'\n'.join([step.friendly_name for step in self.unit_queue])}"
        return build_order_message

    @timed_async
    async def move_interupted_to_pending(self) -> None:
        to_promote: List[int] = []
        for idx, build_step in enumerate(self.started):
            if await build_step.is_interrupted():
                # move back to pending (demote)
                to_promote.append(idx)
        for idx in reversed(to_promote):
            step: BuildStep = self.started.pop(idx)
            step.interrupted_count += 1
            LogHelper.add_log(f"{step} interrupted")
            if isinstance(step, UpgradeBuildStep) and self.bot.already_pending_upgrade(step.upgrade_id) > 0:
                # actually finished
                continue
            if isinstance(step, SCVBuildStep) and step.is_unit_type(UnitTypeId.BUNKER) and step.no_position_count > 10:
                # give up on blocked bunker
                continue
            if step.is_unit() and self.get_queued_count(step.get_unit_type_id()) > 0:
                self.build_queue.insert(0, step)
            elif isinstance(step, SCVBuildStep) and step.unit_being_built:
                # put buildings that are already started at the front of the queue since they're already paid for
                self.interrupted_queue.insert(0, step)
            else:
                self.priority_queue.append(step)
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

    def enact_build_changes(self, detected_enemy_builds: Dict[BuildType, float]) -> None:
        if self.bot.time < self.time_to_deviate_from_build_order:
            # wait so the very initial build order is not disrupted
            return
        # if self.bot.time > 300 or self.bot.townhalls.amount > 2 or BuildType.RUSH not in detected_enemy_builds:
        #     # not a rush
        #     return
        # prioritize blocking ramp
        self.make_one_time_build_change(BuildType.WORKER_RUSH, BuildOrderChange.WORKER_RUSH, detected_enemy_builds)
        self.make_one_time_build_change(BuildType.BATTLECRUISER_RUSH, BuildOrderChange.ANTI_AIR, detected_enemy_builds)
        self.make_one_time_build_change(BuildType.MULTIPLE_REAPER, BuildOrderChange.REAPER, detected_enemy_builds)
        if BuildType.BATTLECRUISER_RUSH not in detected_enemy_builds:
            self.make_one_time_build_change(BuildType.RUSH, BuildOrderChange.RUSH, detected_enemy_builds)
        self.make_one_time_build_change(BuildType.ZERGLING_RUSH, BuildOrderChange.ZERGLING_RUSH, detected_enemy_builds)
        self.make_one_time_build_change(self.bot.enemy_race == Race.Terran, BuildOrderChange.BANSHEE_HARASS, detected_enemy_builds)
        self.make_one_time_build_change(BuildType.STARGATE, BuildOrderChange.ANTI_AIR, detected_enemy_builds)
        self.make_one_time_build_change(BuildType.SPIRE, BuildOrderChange.ANTI_AIR, detected_enemy_builds)
        self.make_one_time_build_change(BuildType.EARLY_EXPANSION, BuildOrderChange.PROXY_BARRACKS, detected_enemy_builds)

        # make persistent changes to build order
        if BuildOrderChange.ANTI_AIR in self.changes_enacted:
            min_vikings = 3
            if BuildType.FLEET_BEACON in detected_enemy_builds or BuildType.BATTLECRUISER_RUSH in detected_enemy_builds:
                min_vikings = 8
            viking_count = self.bot.units.of_type({UnitTypeId.VIKINGFIGHTER, UnitTypeId.VIKINGASSAULT}).amount + self.get_queued_count(UnitTypeId.VIKINGFIGHTER)
            if viking_count < min_vikings:
                self.add_to_build_queue([UnitTypeId.VIKINGFIGHTER] * (min_vikings - viking_count), queue=self.static_queue)

    def make_one_time_build_change(self, enemy_build_type: BuildType | bool, change: BuildOrderChange,
                                detected_enemy_builds: Dict[BuildType, float]) -> None:
        # make one-time changes to build order
        if enemy_build_type not in detected_enemy_builds and enemy_build_type != True:
            return
        if change in self.changes_enacted:
            return
        self.changes_enacted.add(change)
        LogHelper.add_log(f"Enacting build order change: {change.name}")
        
        if change == BuildOrderChange.WORKER_RUSH:
            self.remove_step_from_queue(UnitTypeId.COMMANDCENTER, self.static_queue)
            self.remove_step_from_queue(UnitTypeId.REFINERY, self.static_queue, remove_all=True)
            self.move_between_queues(UnitTypeId.SUPPLYDEPOT, self.static_queue, self.priority_queue, position=0)
            self.add_to_build_queue([UnitTypeId.SUPPLYDEPOT], position=1, queue=self.priority_queue)
        elif change == BuildOrderChange.REAPER:
            # queue one hellion in case of reaper rush
            self.add_to_build_queue([UnitTypeId.HELLION] * 2, position=0, queue=self.priority_queue)
            # swap reactor for techlab (faster, allows marauder)
            for step in self.static_queue:
                if step.is_unit_type(UnitTypeId.BARRACKSREACTOR):
                    self.static_queue.remove(step)
                    self.add_to_build_queue([UnitTypeId.BARRACKSTECHLAB, UnitTypeId.MARAUDER], position=0, queue=self.priority_queue)
                    break
        elif change == BuildOrderChange.RUSH:
            # prioritize bunker and first tank
            self.move_between_queues(UnitTypeId.REAPER, self.static_queue, self.priority_queue)
            in_progress_depots = self.get_in_progress_count(UnitTypeId.SUPPLYDEPOT)
            if BuildType.PROXY in detected_enemy_builds:
                if self.bot.structures([UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED]).amount + in_progress_depots< 2:
                    # make sure to build second depot before bunker
                    self.move_between_queues(UnitTypeId.SUPPLYDEPOT, self.static_queue, self.priority_queue)
                # proxy will hit earlier, really need bunker
                if self.move_between_queues(UnitTypeId.BUNKER, self.static_queue, self.priority_queue):
                    # add a second bunker for low ground
                    self.add_to_build_queue([UnitTypeId.BUNKER], queue=self.static_queue, position=10)
            self.move_between_queues(UnitTypeId.MARINE, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.BARRACKSREACTOR, self.static_queue, self.priority_queue)
            self.move_between_queues(UnitTypeId.SUPPLYDEPOT, self.static_queue, self.priority_queue)
            if self.bot.structures(UnitTypeId.FACTORY).amount == 0 and self.get_in_progress_count(UnitTypeId.FACTORY) == 0:
                self.move_between_queues(UnitTypeId.FACTORY, self.static_queue, self.priority_queue)
            if not self.move_between_queues(UnitTypeId.FACTORYTECHLAB, self.static_queue, self.priority_queue):
                self.add_to_build_queue([UnitTypeId.FACTORYTECHLAB], queue=self.priority_queue)
            if not self.move_between_queues(UnitTypeId.SIEGETANK, self.static_queue, self.priority_queue):
                self.add_to_build_queue([UnitTypeId.SIEGETANK], queue=self.priority_queue)
            # undo banshee harass if enemy rush detected. might still be good vs zerg
            if self.enemy.enemy_race != Race.Zerg:
                self.move_between_queues(UnitTypeId.STARPORT, self.priority_queue, self.static_queue, position=2)
                self.substitute_steps_in_queue(UnitTypeId.STARPORTTECHLAB, [UnitTypeId.VIKINGFIGHTER], self.static_queue)
                self.remove_step_from_queue(UnitTypeId.BANSHEE, self.static_queue, remove_all=True)
                self.remove_step_from_queue(UpgradeId.BANSHEECLOAK, self.static_queue, remove_all=True)
            if BuildType.PROXY not in detected_enemy_builds:
                if self.bot.structures([UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED]).amount + in_progress_depots < 2:
                    # make sure to build second depot before bunker
                    self.move_between_queues(UnitTypeId.SUPPLYDEPOT, self.static_queue, self.priority_queue)
                if self.move_between_queues(UnitTypeId.BUNKER, self.static_queue, self.priority_queue):
                    # add a second bunker for low ground
                    self.add_to_build_queue([UnitTypeId.BUNKER], queue=self.static_queue, position=10)
        elif change == BuildOrderChange.ZERGLING_RUSH:
            self.remove_step_from_queue(UnitTypeId.COMMANDCENTER, self.static_queue)
            # prioritize widowmine, hellion, marine, marine
            self.move_between_queues(UnitTypeId.MARINE, self.static_queue, self.priority_queue, position=0)
            self.move_between_queues(UnitTypeId.MARINE, self.static_queue, self.priority_queue, position=0)
            self.add_to_build_queue([UnitTypeId.WIDOWMINE, UnitTypeId.HELLION], queue=self.priority_queue, position=0)
            if self.bot.structures(UnitTypeId.BUNKER).amount > 0:
                self.remove_step_from_queue(UnitTypeId.BUNKER, self.static_queue, remove_all=True)
        elif change == BuildOrderChange.ANTI_AIR:
            self.remove_step_from_queue(UnitTypeId.STARPORTTECHLAB, self.static_queue)
            self.add_to_build_queue([UnitTypeId.STARPORTREACTOR], queue=self.priority_queue)
            self.remove_step_from_queue(UnitTypeId.BANSHEE, self.static_queue, remove_all=True)
            self.remove_step_from_queue(UnitTypeId.MEDIVAC, self.static_queue)
            self.add_to_build_queue([UnitTypeId.VIKINGFIGHTER] * 2, queue=self.priority_queue)
            self.add_to_build_queue([UnitTypeId.CYCLONE], queue=self.static_queue)
            self.remove_step_from_queue(UpgradeId.BANSHEECLOAK, self.static_queue)
            if enemy_build_type == BuildType.BATTLECRUISER_RUSH:
                self.remove_step_from_queue(UnitTypeId.SIEGETANK, self.static_queue, remove_all=True)
                self.add_to_build_queue([UnitTypeId.STARPORT, UnitTypeId.STARPORTREACTOR], queue=self.static_queue, remove_duplicates=False)
        elif change == BuildOrderChange.BANSHEE_HARASS:
            self.move_between_queues(UnitTypeId.STARPORT, self.static_queue, self.priority_queue)
            self.substitute_steps_in_queue(UnitTypeId.VIKINGFIGHTER, [
                UnitTypeId.STARPORTTECHLAB,
                UpgradeId.BANSHEECLOAK,
                UnitTypeId.BANSHEE], self.static_queue)
            self.add_to_build_queue([UnitTypeId.VIKINGFIGHTER], queue=self.static_queue)
            self.add_to_build_queue([UnitTypeId.BANSHEE], queue=self.static_queue, remove_duplicates=False)
        elif change == BuildOrderChange.PROXY_BARRACKS:
            self.move_between_queues(UnitTypeId.BARRACKS, self.static_queue, self.priority_queue, position=0)
            if self.bot.structures(UnitTypeId.BARRACKS).amount == 0:
                # move second if first hasn't started yet
                self.move_between_queues(UnitTypeId.BARRACKS, self.static_queue, self.priority_queue, position=0)
            # will have a lot of injured marines
            self.add_to_build_queue([UnitTypeId.MEDIVAC], queue=self.priority_queue)
            self.remove_step_from_queue(UnitTypeId.REAPER, self.static_queue)
            self.remove_step_from_queue(UnitTypeId.REAPER, self.priority_queue)
            self.remove_step_from_queue(UnitTypeId.BUNKER, self.priority_queue, remove_all=True)
    
    def move_between_queues(self, unit_type: UnitTypeId, from_queue: List[BuildStep], to_queue: List[BuildStep], position: int | None = None) -> bool:
        for step in from_queue:
            if step.is_unit_type(unit_type):
                from_queue.remove(step)
                if position is not None:
                    to_queue.insert(position, step)
                else:
                    to_queue.append(step)
                if isinstance(step, SCVBuildStep) and step.unit_type_id == UnitTypeId.BUNKER:
                    # clear position in case low-ground needs to move to high-ground location
                    step.position = None
                return True
        return False
    
    def substitute_steps_in_queue(self, from_unit_type: UnitTypeId | UpgradeId,
                                  to_unit_types: List[UnitTypeId | UpgradeId],
                                  queue: List[BuildStep]) -> bool:
        for idx, step in enumerate(queue):
            if step.is_unit_type(from_unit_type):
                queue.remove(step)
                for to_unit_type in to_unit_types:
                    new_step = self.create_build_step(to_unit_type)
                    queue.insert(idx, new_step)
                    idx += 1
                return True
        return False
    
    def remove_step_from_queue(self, unit_type: UnitTypeId | UpgradeId, queue: List[BuildStep], remove_all: bool = False) -> bool:
        removed = False
        for step in queue[:]:
            if isinstance(unit_type, UnitTypeId):
                if step.is_unit_type(unit_type):
                    queue.remove(step)
                    if not remove_all:
                        return True
                    removed = True
            else:
                if step.is_upgrade_type(unit_type):
                    queue.remove(step)
                    return True
        return removed

    @timed
    def add_to_build_queue(self, unit_types: List[UnitTypeId | UpgradeId],
                           position: int | None = None,
                           queue: List[BuildStep] | None = None,
                           remove_duplicates: bool = True) -> List[BuildStep]:
        if queue is None:
            queue = self.build_queue
        all_prereqs: List[UnitTypeId | UpgradeId] = []
        for unit_type in unit_types:
            if isinstance(unit_type, UpgradeId):
                continue
            prereqs = self.production.build_order_with_prereqs(unit_type)
            for prereq in prereqs:
                if isinstance(prereq, UpgradeId) or \
                        self.get_queued_count(prereq) > 0 or \
                        self.get_in_progress_count(prereq) > 0 or \
                        self.bot.structures(prereq).amount > 0:
                    continue
                if prereq != unit_type and prereq not in all_prereqs:
                    all_prereqs.append(prereq)
        unit_types = all_prereqs + unit_types
        
        if remove_duplicates:
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
            # LogHelper.add_log(f"Adding to build queue: {', '.join([step.friendly_name for step in steps_to_add])}")
            if position is not None:
                steps_to_add = queue[:position] + steps_to_add + queue[position:]
                queue.clear()
            queue.extend(steps_to_add)
        return steps_to_add

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

    @timed
    def get_military_queue(self, enemy: Enemy, intel: EnemyIntel) -> Tuple[List[UnitTypeId | UpgradeId], List[UnitTypeId | UpgradeId]]:
        worker_supply_cap = min(self.workers.max_workers, self.bot.workers.amount * 1.15)
        military_cap = self.bot.supply_cap - worker_supply_cap
        enemy_army = enemy.get_army(include_scouts=True, seconds_since_killed=60)
        ideal_composition = self.counter.get_counters(enemy_army)
        current_composition = UnitTypes.count_units_by_type(self.bot.units)
        if not ideal_composition:
            # if no enemy units, current army is doing pretty well?
            for unit_type, count in current_composition.items():
                ideal_composition[unit_type] = count
        ideal_supply = 0
        for unit_type, count in ideal_composition.items():
            if unit_type in (UnitTypeId.MULE, UnitTypeId.SCV) or count < 0:
                continue
            supply_cost: int = self.unit_types.get_unit_info(unit_type)["supply"]
            ideal_supply += supply_cost * count
        # scale composition to fit military cap
        
        queue: List[UnitTypeId | UpgradeId] = []
        priority_queue: List[UnitTypeId | UpgradeId] = []
        if UnitTypeId.RAVEN not in ideal_composition:
            # have at least one raven for detection
            ideal_composition[UnitTypeId.RAVEN] = 0.01
        if UnitTypeId.VIKINGFIGHTER not in ideal_composition:
            # have at least one viking for scouting
            ideal_composition[UnitTypeId.VIKINGFIGHTER] = 0.01
        # queued_supply = 0

        # buildable_percentage = min(1.0, military_cap / ideal_supply) if ideal_supply > 0 else 0
        buildable_percentage = min(3.0, military_cap / ideal_supply) if ideal_supply > 0 else 0
        # while queued_supply < self.bot.supply_left and len(queue) < 10:
        for unit_type, count in ideal_composition.items():
            if unit_type in (UnitTypeId.MULE, UnitTypeId.SCV):
                continue
            ideal_count = math.ceil(count * buildable_percentage)
            existing_count = current_composition.get(unit_type, 0)
            in_progress_count = self.get_in_progress_count(unit_type)
            queued_count = self.get_queued_count(unit_type, self.priority_queue + self.static_queue)

            needed_count = ideal_count - existing_count - in_progress_count - queued_count
            if needed_count > 0:
                # queued_supply += needed_count * self.unit_types.get_unit_info(unit_type)["supply"]
                if needed_count >= 5 or existing_count + in_progress_count + queued_count == 0:
                    priority_queue.append(unit_type)
                    needed_count -= 1
                queue.extend([unit_type] * needed_count)
        
        recent_drops = intel.get_recent_drop_locations(within_seconds=120)
        if len(recent_drops) > 0:
            widowmines = self.bot.units(UnitTypeId.WIDOWMINE)
            in_progress_and_queued_widowmines = self.get_queued_count(UnitTypeId.WIDOWMINE, queue=self.started + self.priority_queue + self.static_queue)
            needed_mine_count = len(recent_drops) - len(widowmines) + in_progress_and_queued_widowmines
            if needed_mine_count > 0:
                # need more widowmines for drop defense
                priority_queue.append(UnitTypeId.WIDOWMINE)
                if needed_mine_count > 1:
                    queue.extend([UnitTypeId.WIDOWMINE] * (needed_mine_count - 1))
        
        return (queue, priority_queue)

    @timed
    def queue_supply(self) -> None:
        in_static_queue = self.get_queued_count(UnitTypeId.SUPPLYDEPOT, queue=self.static_queue) > 0
        if 0 < self.bot.supply_cap < 200 and not in_static_queue:
            in_progress_count = self.get_in_progress_count(UnitTypeId.SUPPLYDEPOT)
            in_progress_ccs = self.bot.townhalls.filter(lambda cc: not cc.is_ready)
            for cc in in_progress_ccs:
                # a complete cc is worth 2 depots so multiply progress by 2
                in_progress_count += (cc.build_progress + 0.15) * 2
            in_progress_count = math.floor(in_progress_count)
            
            supply_percent_remaining = self.bot.supply_left / self.bot.supply_cap
            if self.bot.supply_left < 10 or supply_percent_remaining <= 0.2:
                needed_count = 1
                # queue another if supply is very low
                if (self.bot.supply_left < 2 or supply_percent_remaining <= 0.1):
                    needed_count += 1
                if (self.bot.supply_left == 0):
                    needed_count += 1
                if in_progress_count < needed_count:
                    self.add_to_build_queue([UnitTypeId.SUPPLYDEPOT] * (needed_count - in_progress_count), queue=self.priority_queue)

    def get_in_progress_count(self, unit_type: UnitTypeId | UpgradeId) -> int:
        count = 0
        for build_step in self.started + self.interrupted_queue:
            if build_step.is_unit_type(unit_type):
                count += 1
        return count

    def get_queued_count(self, unit_types: UnitTypeId | List[UnitTypeId], queue: List[BuildStep] | None = None) -> int:
        count = 0
        if isinstance(unit_types, UnitTypeId):
            unit_types = [unit_types]
        if queue is None:
            queue = self.priority_queue + self.static_queue + self.build_queue
        for build_step in queue:
            for unit_type in unit_types:
                if build_step.is_unit_type(unit_type):
                    count += 1
        return count

    @timed
    def queue_command_center(self, army_ratio: float, detected_enemy_builds) -> None:
        if self.bot.time < 100:
            return
        if self.bot.townhalls.amount == 2 and self.bot.townhalls.flying:
            # don't queue another expansion if current one is still in air
            # probably unsafe or it would have landed
            return
        if BuildType.RUSH in detected_enemy_builds and self.bot.time < 160:
            # don't expand too early during rush
            return
        if len(detected_enemy_builds) == 0 and self.bot.structures(UnitTypeId.STARPORT).amount == 0:
            # wait for starport if not getting rushed
            return

        projected_worker_capacity = self.workers.get_mineral_capacity()
        cc_count = self.get_queued_count(UnitTypeId.COMMANDCENTER, self.all_steps)
        projected_worker_capacity += cc_count * 16

        # adds number of townhalls to account for near-term production
        projected_worker_count = min(self.workers.max_workers,
                                     len(self.workers.assignments_by_job[WorkerJobType.MINERALS]) + len(self.bot.townhalls) * 4)
        surplus_worker_count = projected_worker_count - projected_worker_capacity
        needed_cc_count = math.ceil(surplus_worker_count / 16)
        if army_ratio < 0.65 and self.bot.townhalls.amount >= 2 and self.bot.minerals <= 500:
            # delay expansion if army low and already have 2 bases, unless sitting on enough minerals
            needed_cc_count -= 1
        
        if needed_cc_count > cc_count:
            # expand if running out of room for workers at current bases
            self.add_to_build_queue([UnitTypeId.COMMANDCENTER] * (needed_cc_count - cc_count), queue=self.priority_queue)
        # elif len(self.bot.townhalls) == 1 and cc_count == 0 and self.bot.time > 160 and army_ratio > 1.0:
        #     self.remove_step_from_queue(UnitTypeId.COMMANDCENTER, self.priority_queue)
        #     self.add_to_build_queue([UnitTypeId.COMMANDCENTER], queue=self.priority_queue, position=0)

    @timed
    def queue_townhall_work(self, detected_enemy_builds: Dict[BuildType, float]) -> None:
        if self.bot.time < 15:
            # pause workers to save for first expansion
            return
        if self.bot.workers.amount >= 15 and self.bot.structures(UnitTypeId.BARRACKS).amount == 0:
            # hold off on workers until barracks started
            return
        if BuildType.WORKER_RUSH in detected_enemy_builds and self.bot.time < 180 and self.bot.structures.of_type([UnitTypeId.SUPPLYDEPOT, UnitTypeId.BARRACKS]).amount < 3:
            # hold off on workers during worker rush until wall is up
            return

        available_townhalls = self.bot.townhalls.filter(lambda cc: cc.is_ready and (not cc.orders or cc.orders[0].progress > 0.85) and not cc.is_flying)
        available_command_centers = available_townhalls.filter(lambda cc: cc.type_id == UnitTypeId.COMMANDCENTER)
        if available_command_centers and self.bot.time > 90:
            orbital_count = len(self.bot.townhalls.of_type(UnitTypeId.ORBITALCOMMAND))
            in_progress_orbital_count = self.get_in_progress_count(UnitTypeId.ORBITALCOMMAND)
            if orbital_count == 0 and in_progress_orbital_count == 0:
                self.add_to_build_queue([UnitTypeId.ORBITALCOMMAND], queue=self.priority_queue, position=0)
            elif orbital_count < 3 and in_progress_orbital_count == 0 and self.bot.structures(UnitTypeId.STARPORT):
                # wait on starport before second orbital
                self.add_to_build_queue([UnitTypeId.ORBITALCOMMAND], queue=self.priority_queue, position=0)
                return
            elif self.bot.minerals >= 150 and self.bot.vespene >= 150 and self.bot.structures(UnitTypeId.ENGINEERINGBAY).ready:
                self.add_to_build_queue([UnitTypeId.PLANETARYFORTRESS], queue=self.priority_queue, position=0)
                return

        worker_build_capacity: int = len(available_townhalls)
        cc_queued_upgrade_count = self.get_queued_count([UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS],
                                                        self.interrupted_queue + self.priority_queue)
        worker_build_capacity -= cc_queued_upgrade_count
        desired_worker_count = min(self.workers.max_workers, self.bot.townhalls.amount * 25)
        number_to_build = desired_worker_count - len(self.workers.assignments_by_worker)
        if (worker_build_capacity > 0 and number_to_build > 0):
            self.add_to_build_queue([UnitTypeId.SCV] * min(number_to_build, worker_build_capacity), queue=self.priority_queue, position=0)

    @timed
    def queue_refinery(self) -> None:
        refinery_count = len(self.bot.gas_buildings.ready) + self.get_in_progress_count(UnitTypeId.REFINERY) + self.get_queued_count(UnitTypeId.REFINERY)
        # build refinery if less than 2 per town hall (function is only called if gas is needed but no room to move workers)
        if self.bot.townhalls.ready:
            geysirs = self.bot.vespene_geyser.in_distance_of_group(
                distance=10, other_units=self.bot.townhalls.ready
            )
            if refinery_count < len(geysirs):
                self.add_to_build_queue([UnitTypeId.REFINERY], queue=self.priority_queue)
        # should also build a new one if current bases run out of resources

    @timed
    def queue_production(self, only_build_units: bool):
        if not self.bot.structures(UnitTypeId.STARPORT):
            return
        # add more barracks/factories/starports to handle backlog of pending affordable units
        production_items: List[UnitTypeId] = []
        available_resources: Cost = Cost(self.bot.minerals, self.bot.vespene)

        # find first shortage, unit_queue hasn't been added to build_queue yet
        for build_step in self.priority_queue + self.static_queue + self.build_queue + self.unit_queue:
            if only_build_units:
                if not build_step.is_unit():
                    continue
            elif not build_step.is_unit() or build_step.get_unit_type_id() == UnitTypeId.SCV:
                # subtract cost of items that aren't limited by barracks/factory/starport capacity
                available_resources.minerals -= build_step.cost.minerals
                available_resources.vespene -= build_step.cost.vespene
                if available_resources.minerals < 0 or available_resources.vespene < 0:
                    break
            else:
                # accumulate production items. will only be relevant if there are still available_resources
                production_items.append(build_step.get_unit_type_id())

        extra_production: List[UnitTypeId] = self.production.additional_needed_production(production_items, available_resources)
        # only add if not already in progress
        extra_production = self.remove_in_progress_from_list(extra_production) # type: ignore
        self.add_to_build_queue(extra_production, position=0, queue=self.static_queue) # type: ignore

    @timed
    def queue_marines(self, detected_enemy_builds: Dict[BuildType, float], army_ratio: float) -> None:
        if self.tactics.is_active(Tactic.PROXY_BARRACKS):
            # if enemy expands early, prioritize marines to punish
            self.add_to_build_queue([UnitTypeId.MARINE], queue=self.priority_queue, position=0)
            return
        # use excess minerals and idle barracks
        need_early_marines: bool = self.bot.time < 300 and army_ratio < 0.8 and \
            (BuildType.RUSH in detected_enemy_builds or len(cy_closer_than(self.bot.enemy_units, 20, self.map.natural_position)) > 2)
            
        if need_early_marines and self.bot.minerals >= 50 and self.bot.structures(UnitTypeId.BARRACKSREACTOR):
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

    @timed
    def queue_medivacs(self) -> None:
        marine_count = self.bot.units.of_type(UnitTypeId.MARINE).amount
        marauder_count = self.bot.units.of_type(UnitTypeId.MARAUDER).amount
        for bunker in self.bot.structures.of_type(UnitTypeId.BUNKER):
            marine_count += sum(p.type_id == UnitTypeId.MARINE for p in bunker.passengers)
            marauder_count += sum(p.type_id == UnitTypeId.MARAUDER for p in bunker.passengers)
        medivac_count = self.bot.units.of_type(UnitTypeId.MEDIVAC).amount + self.get_in_progress_count(UnitTypeId.MEDIVAC)
        desired_medivac_count = min(8, math.floor(marine_count / 8 + marauder_count / 4 + 0.5))
        queue_count = desired_medivac_count - medivac_count
        # use excess minerals and idle starports
        if queue_count > 0:
            self.add_to_build_queue([UnitTypeId.MEDIVAC] * queue_count, queue=self.static_queue)

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

    @timed
    def queue_upgrade(self, build_order_changes: Set[BuildOrderChange]) -> None:
        for facility_type in self.upgrade_building_types:
            next_upgrade = self.upgrades.next_upgrade(facility_type, build_order_changes)
            if next_upgrade is None or self.upgrade_is_in_progress(next_upgrade):
                continue
            if self.bot.structures(facility_type).ready.idle:
                self.add_to_build_queue([next_upgrade], queue=self.static_queue)
            elif self.bot.townhalls.amount > 2 and self.bot.time > 300 and self.get_in_progress_count(facility_type) == 0:
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
                    self.add_to_build_queue(new_build_steps, queue=self.static_queue, position=0)

    def upgrade_is_in_progress(self, upgrade_type: UpgradeId) -> bool:
        for build_step in self.started:
            if build_step.is_upgrade_type(upgrade_type):
                return True
        return False

    @timed
    def queue_planetary(self) -> None:
        planetary_count = len(self.bot.structures.of_type(UnitTypeId.PLANETARYFORTRESS)) + self.get_in_progress_count(UnitTypeId.PLANETARYFORTRESS)
        cc_count = len(self.bot.structures.of_type(UnitTypeId.COMMANDCENTER))
        if self.bot.time > 500 and planetary_count < cc_count:
            self.add_to_build_queue(self.production.build_order_with_prereqs(UnitTypeId.PLANETARYFORTRESS))

    @timed
    def queue_turret(self, intel: EnemyIntel) -> None:
        if intel.enemy_race == Race.Protoss and UnitTypeId.STARGATE not in intel.first_building_time:
            # protoss without stargate likely adepts or zealots, don't build turrets
            return
        if self.bot.structures(UnitTypeId.ENGINEERINGBAY).ready:
            turrets = self.bot.structures.of_type(UnitTypeId.MISSILETURRET)
            turret_count = len(turrets.ready)
            construction_started_count = len(turrets) - turret_count
            in_progress_count = self.get_in_progress_count(UnitTypeId.MISSILETURRET)
            construction_pending_count = in_progress_count - construction_started_count
            if construction_pending_count > 0:
                # don't queue another until this starts to avoid building two at same base
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
    
    @timed_async
    async def queue_bunker(self, main_army_staging_location: Point2) -> None:
        in_progress_bunkers = self.get_in_progress_count(UnitTypeId.BUNKER)
        if in_progress_bunkers > 0:
            return
        queued_bunkers = self.get_queued_count(UnitTypeId.BUNKER)
        if queued_bunkers > 0:
            return
        if main_army_staging_location._distance_squared(self.bot.start_location) < 225:
            return
        bunkers = self.bot.structures.of_type(UnitTypeId.BUNKER)
        closest_bunker = cy_closest_to(main_army_staging_location, bunkers) if bunkers else None
        if closest_bunker and cy_distance_to(closest_bunker.position, main_army_staging_location) < 10:
            # already have a bunker near main army
            return
        path_to_enemy = self.map.get_path(main_army_staging_location, self.bot.enemy_start_locations[0])
        path_to_enemy.draw(self.bot)
        placement_position = main_army_staging_location
        position_is_valid = await self.bot.can_place_single(UnitTypeId.BUNKER, placement_position)
        while not position_is_valid and len(path_to_enemy.zones) > 1:
            next_waypoint = path_to_enemy.zones[1].midpoint
            towards_distance = min(1, cy_distance_to(placement_position, next_waypoint))
            placement_position = Point2(cy_towards(placement_position, next_waypoint, towards_distance))
            if placement_position.manhattan_distance(next_waypoint) < 0.1:
                path_to_enemy.zones.pop(0)
            if closest_bunker and cy_distance_to(closest_bunker.position, placement_position) < 10:
                break
            position_is_valid = await self.bot.can_place_single(UnitTypeId.BUNKER, placement_position)
            
        if position_is_valid:
            new_steps = self.add_to_build_queue([UnitTypeId.BUNKER], queue=self.static_queue)
            if new_steps:
                for bunker_step in new_steps:
                    if isinstance(bunker_step, SCVBuildStep) and bunker_step.unit_type_id == UnitTypeId.BUNKER:
                        bunker_step.position = placement_position

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

    def update_started_structure(self, started_structure: Unit) -> None:
        for in_progress_step in self.started:
            # skip upgrades and steps that already have a structure assigned
            if isinstance(in_progress_step, UpgradeId) or in_progress_step.get_structure_being_built():
                continue
            if in_progress_step.is_unit_type(started_structure.type_id):
                if in_progress_step.unit_in_charge and in_progress_step.unit_in_charge.type_id == UnitTypeId.SCV:
                    try:
                        in_progress_step.unit_in_charge = UnitReferenceHelper.get_updated_unit_reference(in_progress_step.unit_in_charge)
                    except UnitReferenceHelper.UnitNotFound:
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
                    try:
                        builder = UnitReferenceHelper.get_updated_unit_reference(builder)
                        if in_progress_step.is_unit_type(UnitTypeId.REFINERY):
                            self.workers.update_assigment(builder, WorkerJobType.VESPENE, completed_structure)
                        else:
                            self.workers.set_as_idle(builder)
                    except UnitReferenceHelper.UnitNotFound:
                        pass
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
                if build_step.is_unit_type(UnitTypeId.COMMANDCENTER) \
                        and len(self.bot.townhalls.ready) == 1:
                    self.intel.add_detected_build(BuildType.RUSH)
                break

    async def execute_pending_builds(self, only_build_units: bool, detected_enemy_builds: Dict[BuildType, float]) -> Cost:
        allow_skip = self.bot.time > self.time_to_deviate_from_build_order
        remaining_resources: Cost = await self.build_from_queue(self.interrupted_queue, only_build_units, detected_enemy_builds, allow_skip)
        if remaining_resources.minerals > 0:
            remaining_resources: Cost = await self.build_from_queue(self.priority_queue, only_build_units, detected_enemy_builds, allow_skip, remaining_resources)
        if remaining_resources.minerals > 0:
            remaining_resources = await self.build_from_queue(self.static_queue, only_build_units, detected_enemy_builds, allow_skip, remaining_resources)
        if remaining_resources.minerals > 0:
            remaining_resources = await self.build_from_queue(self.build_queue, only_build_units, detected_enemy_builds, allow_skip, remaining_resources)
        return remaining_resources

    @timed_async
    async def build_from_queue(self, build_queue: List[BuildStep], only_build_units: bool, detected_enemy_builds: Dict[BuildType, float],
                               allow_skip: bool = True, remaining_resources: Cost | None = None) -> Cost:
        build_response = BuildResponseCode.QUEUE_EMPTY
        execution_index = -1
        failed_types: List[UnitTypeId] = []
        if remaining_resources is None:
            remaining_resources = Cost(self.bot.minerals, self.bot.vespene)
            for pending in self.started:
                if isinstance(pending, SCVBuildStep) \
                        and pending.unit_being_built is None \
                        and pending.unit_in_charge and not pending.unit_in_charge.is_constructing_scv:
                    # if we have pending builds that haven't started yet, subtract their cost from available resources
                    remaining_resources = remaining_resources - pending.cost

        while execution_index < len(build_queue):
            execution_index += 1
            # if execution_index > 10:
            #     break
            try:
                build_step = build_queue[execution_index]
            except IndexError:
                break
            # skip steps for various reasons
            if isinstance(build_step, SCVBuildStep) and build_step.unit_being_built and build_step.unit_being_built.build_progress == 1.0:
                # already built
                build_queue.pop(execution_index)
                execution_index -= 1
                continue
            if build_step.get_unit_type_id() in failed_types:
                continue
            if self.bot.supply_left < build_step.supply_cost and build_step.supply_cost > 0:
                build_response = BuildResponseCode.NO_SUPPLY
                if not allow_skip:
                    remaining_resources.minerals = 0
                    break
                continue
            if only_build_units and not build_step.is_unit() \
                    and not build_step.is_unit_type(UnitTypeId.COMMANDCENTER) \
                    and not build_step.is_unit_type(UnitTypeId.SUPPLYDEPOT) \
                    and not build_step.is_unit_production_facility() \
                    and not (isinstance(build_step, SCVBuildStep) and build_step.unit_being_built is not None):
                continue
            time_since_last_cancel = self.bot.time - build_step.last_cancel_time
            if time_since_last_cancel < 10:
                continue
            
            production_readiness = 1.0
            if isinstance(build_step, StructureBuildStep) or isinstance(build_step, UpgradeBuildStep):
                production_readiness = build_step.get_readiness_to_build()
                if production_readiness < 0.8:
                    # don't reserve resources if production not close to ready
                    build_response = BuildResponseCode.NO_FACILITY
                    if not allow_skip:
                        remaining_resources.minerals = 0
                        break
                    continue

            if not build_step.tech_requirements_met():
                build_response = BuildResponseCode.NO_TECH
                if not allow_skip:
                    remaining_resources.minerals = 0
                    break
                # skip if missing tech
                failed_types.append(build_step.get_unit_type_id())
                continue

            percent_affordable = 1.0
            added_cost: Cost = Cost(0, 0)
            if not isinstance(build_step, SCVBuildStep) or build_step.unit_being_built is None:
                percent_affordable = self.percent_affordable(remaining_resources, build_step.cost)
                added_cost = build_step.cost
                remaining_resources = remaining_resources - added_cost
            if percent_affordable < 1.0:
                if only_build_units:
                    # builder_type = build_step.builder_type
                    # if build_step.get_unit_type_id() in self.production.needs_tech_lab:
                    #     builder_type = self.production.add_on_type_lookup[build_step.builder_type][UnitTypeId.TECHLAB]
                    # skip ahead more aggressively to try to use any production capacity
                    remaining_resources = remaining_resources + added_cost
                    continue
                if remaining_resources.vespene < 0:
                    # don't reserve minerals for missing gas
                    remaining_resources.minerals -= remaining_resources.vespene
                build_response = BuildResponseCode.NO_RESOURCES
                if isinstance(build_step, SCVBuildStep):
                    if (build_step.is_unit_type(UnitTypeId.BARRACKS)
                            and BuildType.EARLY_EXPANSION in self.intel.enemy_builds_detected
                            and self.bot.time < 200
                        ) or (percent_affordable >= 0.75
                            and self.bot.tech_requirement_progress(build_step.unit_type_id) == 1.0):
                        await build_step.position_worker(self.special_locations, detected_enemy_builds, self.floating_building_destinations)
                if remaining_resources.minerals < 50:
                    break
                continue

            if production_readiness != 1.0:
                # reserve resources if production is almost ready
                failed_types.append(build_step.get_unit_type_id())
                continue

            # XXX slightly slow
            build_response = await build_step.execute(self.special_locations, detected_enemy_builds, self.floating_building_destinations)
            if build_response == BuildResponseCode.SUCCESS:
                LogHelper.add_log(f"Started building {build_step}")
                self.started.append(build_queue.pop(execution_index))
                execution_index -= 1
                if build_step.interrupted_count > 5:
                    # can't trust that this actually got built
                    continue
                # remaining_resources.minerals = 0
                # break
            else:
                if build_response != BuildResponseCode.NO_FACILITY:
                    LogHelper.add_log(f"failed to start {build_step}: {build_response}")
                if not allow_skip:
                    remaining_resources.minerals = 0
                    break
                if self.bot.time > 60:
                    remaining_resources = remaining_resources + added_cost
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
                            execution_index -= 1
                            # remaining_resources.minerals = 0
                            # return remaining_resources
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
    
    def mark_position_invalid_by_worker_tag(self, worker_tag: int) -> None:
        for idx, build_step in enumerate(self.started):
            if isinstance(build_step, SCVBuildStep) and build_step.unit_in_charge is not None:
                if build_step.unit_in_charge.tag == worker_tag:
                    build_step.set_interrupted()
                    self.started.pop(idx)
                    self.interrupted_queue.insert(0, build_step)
                    break
