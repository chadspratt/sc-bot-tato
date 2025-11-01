import math
import random
from loguru import logger
from typing import Dict, List, Union

from sc2.ids.ability_id import AbilityId
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.game_data import Cost
from sc2.data import Race

from bottato.unit_types import UnitTypes
from bottato.build_step import BuildStep, ResponseCode
from bottato.economy.workers import Workers, JobType
from bottato.economy.production import Production
from bottato.mixins import TimerMixin, UnitReferenceMixin
from bottato.upgrades import Upgrades
from bottato.special_locations import SpecialLocations, SpecialLocation
from bottato.map.map import Map
from bottato.build_starts import BuildStarts


class BuildOrder(TimerMixin, UnitReferenceMixin):
    # gets processed first, for supply depots and workers
    priority_queue: List[BuildStep] = []
    # initial build order and interrupted builds
    static_queue: List[BuildStep] = []
    # dynamic queue for army units and production
    build_queue: List[BuildStep] = []
    started: List[BuildStep] = []
    complete: List[BuildStep] = []
    # next_unfinished_step_index: int
    tech_tree: Dict[UnitTypeId, List[UnitTypeId]] = {}
    rush_defense_enacted: bool = False

    def __init__(self, build_name: str, bot: BotAI, workers: Workers, production: Production, map: Map):
        self.recently_completed_units: List[Unit] = []
        # self.recently_completed_transformations: List[UnitTypeId] = []
        self.recently_started_units: List[Unit] = []
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.production: Production = production
        self.map: Map = map
        for unit_type in BuildStarts.get_build_start(build_name):
            step = BuildStep(unit_type, bot, workers, production, map)
            self.static_queue.append(step)
        self.upgrades = Upgrades(bot)
        self.special_locations = SpecialLocations(ramp=self.bot.main_base_ramp)
        # self.build_a_worker: BuildStep = None
        # self.supply_build_step: BuildStep = None
        logger.debug(f"Starting position: {self.bot.start_location}")
        # self.queue_unit_type(UnitTypeId.BATTLECRUISER)

    async def update_references(self, units_by_tag: dict[int, Unit]) -> None:
        self.start_timer("update_references")
        logger.debug(
            f"pending={','.join([step.friendly_name for step in self.static_queue])}"
        )
        logger.debug(
            f"started={','.join([step.friendly_name for step in self.started])}"
        )
        for build_step in self.all_steps:
            build_step.update_references(units_by_tag)
            logger.debug(f"started step {build_step}")
            build_step.draw_debug_box()
        await self.move_interupted_to_pending()
        self.stop_timer("update_references")

    @property
    def all_steps(self) -> List[BuildStep]:
        return self.started + self.priority_queue + self.static_queue + self.build_queue

    async def move_interupted_to_pending(self) -> None:
        self.start_timer("move_interupted_to_pending")
        to_promote = []
        for idx, build_step in enumerate(self.started):
            logger.debug(
                f"In progress {build_step.unit_type_id} {build_step.upgrade_id}"
                f"> Builder {build_step.unit_in_charge}"
            )
            if await build_step.is_interrupted():
                logger.debug(f"{build_step} Is interrupted!")
                # move back to pending (demote)
                to_promote.append(idx)
                if build_step.unit_being_built is None or build_step.unit_being_built == build_step.unit_in_charge:
                    build_step.is_in_progress = False
                    if build_step.unit_type_id == UnitTypeId.COMMANDCENTER:
                        # if expansion was cancelled, clear position so it can be retried
                        build_step.position = None
                continue
            elif self.bot.enemy_units and build_step.position and UnitTypeId.SCV in build_step.builder_type and build_step.unit_in_charge:
                if build_step.position.distance_to(self.bot.start_location) < 15:
                    # don't interrupt builds in main base
                    continue
                threats = self.bot.enemy_units.filter(lambda u: u.can_attack_ground and u.type_id not in (UnitTypeId.MULE, UnitTypeId.OBSERVER, UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.OVERLORD, UnitTypeId.OVERSEER))
                if threats:
                    closest_threat = threats.closest_to(build_step.unit_in_charge)
                    enemy_is_close = closest_threat.distance_to_squared(build_step.unit_in_charge) < 225 # 15 squared
                    if not enemy_is_close:
                        continue
                    logger.debug(f"{build_step} Too close to enemy!")
                    if build_step.unit_in_charge:
                        self.workers.update_job(build_step.unit_in_charge, JobType.IDLE)
                        build_step.unit_in_charge(AbilityId.HALT)
                        build_step.unit_in_charge = None
                    # move back to pending (demote)
                    to_promote.append(idx)
        for idx in reversed(to_promote):
            step: BuildStep = self.started.pop(idx)
            step.interrupted_count += 1
            if step.interrupted_count > 10:
                logger.info(f"{step} interrupted too many times, removing from build order")
                continue
            if step.unit_type_id not in UnitTypes.TERRAN:
                self.priority_queue.insert(0, step)
            else:
                self.build_queue.insert(0, step)
        for structure in self.bot.structures_without_construction_SCVs:
            # somehow the build step got lost, re-add it
            if structure.health_percentage > 0.05:
                for step in self.all_steps:
                    if step.unit_being_built and step.unit_being_built != True and step.unit_being_built.tag == structure.tag:
                        break
                else:
                    build_step = self.create_build_step(structure.type_id)
                    build_step.unit_being_built = structure
                    self.priority_queue.insert(0, build_step)
        self.stop_timer("move_interupted_to_pending")

    def enact_rush_defense(self) -> None:
        if self.bot.time > 300 or self.bot.townhalls.amount > 2:
            # not a rush
            return
        if self.bot.enemy_race == Race.Terran:
            # queue one hellion in case of reaper rush
            if self.bot.enemy_units(UnitTypeId.REAPER).amount > 0:
                self.add_to_build_queue([UnitTypeId.HELLION], position=0, queue=self.priority_queue)
                # swap reactor for techlab (faster, allows marauder)
                for step in self.static_queue:
                    if step.unit_type_id == UnitTypeId.BARRACKSREACTOR:
                        self.static_queue.remove(step)
                        self.add_to_build_queue([UnitTypeId.BARRACKSTECHLAB, UnitTypeId.MARAUDER], position=0, queue=self.priority_queue)
                        break
        if self.bot.structure_type_build_progress(UnitTypeId.BARRACKSREACTOR) == 1:
            training_marine_count = len([step for step in self.started if step.unit_type_id == UnitTypeId.MARINE])
            if training_marine_count < 2:
                logger.debug("rush detected, queuing 2 marines immediately")
                self.add_to_build_queue([UnitTypeId.MARINE for x in range(2 - training_marine_count)], position=0, queue=self.priority_queue)
        if self.rush_defense_enacted:
            return
        self.rush_defense_enacted = True
        # for step in self.static_queue:
        #     if step.unit_type_id == UnitTypeId.BARRACKSREACTOR:
        #         self.static_queue.remove(step)
        #         self.priority_queue.append(step)
        #         break
        if self.bot.structures(UnitTypeId.SUPPLYDEPOT).amount < 2:
            # make sure to build second depot before bunker
            for step in self.static_queue:
                if step.unit_type_id == UnitTypeId.SUPPLYDEPOT:
                    self.static_queue.remove(step)
                    self.priority_queue.append(step)
                    break
        for step in self.static_queue:
            if step.unit_type_id == UnitTypeId.BUNKER:
                self.static_queue.remove(step)
                self.priority_queue.append(step)
                break

    @property
    def remaining_cap(self) -> int:
        remaining = self.bot.supply_left
        # for step in self.pending:
        # for step in self.build_queue:
        #     if step.unit_type_id:
        #         remaining -= self.bot.calculate_supply_cost(step.unit_type_id)
        return remaining

    async def execute(self, army_ratio: float, rush_detected: bool):
        self.start_timer("build_order.execute")
        self.build_queue.clear()

        # if self.static_queue and self.static_queue[0].unit_type_id in (UnitTypeId.ORBITALCOMMAND, UnitTypeId.SUPPLYDEPOT):
        #     self.priority_queue.append(self.static_queue.pop(0))

        only_build_units = False
        # XXX queue workers more aggressively
        # switch to dynamic build later, put SCVs in static
        self.queue_worker()
        self.queue_supply()
        self.queue_command_center(rush_detected)
        if len(self.static_queue) < 45:
            self.queue_upgrade()
            self.queue_turret()
            self.queue_planetary()
            self.queue_production()

            self.build_queue.extend(self.unit_queue)

            only_build_units = army_ratio > 0.0 and army_ratio < 0.8

        needed_resources: Cost = self.get_first_resource_shortage(only_build_units)

        self.start_timer("redistribute_workers")
        moved_workers = await self.workers.redistribute_workers(needed_resources)
        self.stop_timer("redistribute_workers")
        logger.debug(f"needed gas {needed_resources.vespene}, minerals {needed_resources.minerals}, moved workers {moved_workers}")

        if len(self.static_queue) < 30:
            self.queue_refinery()

        await self.execute_pending_builds(only_build_units, rush_detected)
        
        self.bot.client.debug_text_screen(self.get_build_queue_string(), (0.01, 0.1))
        self.stop_timer("build_order.execute")
    
    def get_build_queue_string(self):
        build_order_message = f"started={'\n'.join([step.friendly_name for step in self.started])}"
        build_order_message += f"\npriority={'\n'.join([step.friendly_name for step in self.priority_queue])}"
        build_order_message += f"\nstatic={'\n'.join([step.friendly_name for step in self.static_queue])}"
        build_order_message += f"\nbuild_queue={'\n'.join([step.friendly_name for step in self.build_queue])}"
        build_order_message += f"\nunit_queue={'\n'.join([step.friendly_name for step in self.unit_queue])}"
        return build_order_message

    def queue_units(self, unit_types: List[UnitTypeId]) -> None:
        self.start_timer("build_order.queue_military")
        self.unit_queue = [self.create_build_step(unit_type) for unit_type in unit_types]
        self.stop_timer("build_order.queue_military")

    def queue_worker(self) -> None:
        self.start_timer("get_queued_worker")
        if len(self.bot.townhalls) > 1 or self.bot.time > 300:
            command_center_upgrade_pending = False
            if self.static_queue and self.static_queue[0].unit_type_id in (UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS):
                command_center_upgrade_pending = True
            elif self.build_queue and self.build_queue[0].unit_type_id in (UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS):
                command_center_upgrade_pending = True
            elif self.started:
                for build_step in self.started:
                    if build_step.unit_type_id in (UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS):
                        if build_step.unit_in_charge.is_idle:
                            # make sure the upgrade actually starts
                            command_center_upgrade_pending = True
                            break
            available_townhalls = self.bot.townhalls.filter(lambda cc: cc.is_ready and cc.is_idle and not cc.is_flying)
            worker_build_capacity: int = len(available_townhalls)
            if command_center_upgrade_pending:
                worker_build_capacity = len(available_townhalls.filter(lambda cc: cc.type_id != UnitTypeId.COMMANDCENTER))
            desired_worker_count = self.workers.max_workers
            # desired_worker_count = max(30, self.bot.supply_cap / 3)
            logger.debug(f"worker_build_capacity={worker_build_capacity}")
            number_to_build = desired_worker_count - len(self.workers.assignments_by_worker)
            if (
                worker_build_capacity > 0
                and number_to_build > 0
            ):
                self.add_to_build_queue([UnitTypeId.SCV for x in range(min(number_to_build, worker_build_capacity))], queue=self.priority_queue)
        self.stop_timer("get_queued_worker")

    def queue_supply(self) -> None:
        self.start_timer("queue_supply")
        in_static_queue = max([build_step.unit_type_id == UnitTypeId.SUPPLYDEPOT for build_step in self.static_queue], default=False)
        if 0 < self.bot.supply_cap < 200 and not in_static_queue:
            in_progress_count = self.get_in_progress_count(UnitTypeId.SUPPLYDEPOT)
            supply_percent_remaining = self.bot.supply_left / self.bot.supply_cap
            if self.bot.supply_left < 10 or supply_percent_remaining <= 0.2:
                needed_count = 1
                # queue another if supply is very low
                if (self.bot.supply_left < 2 or supply_percent_remaining <= 0.1):
                    needed_count += 1
                if in_progress_count < needed_count:
                    self.add_to_build_queue([UnitTypeId.SUPPLYDEPOT for x in range(needed_count - in_progress_count)], queue=self.priority_queue)
        self.stop_timer("queue_supply")

    def get_in_progress_count(self, unit_type: UnitTypeId) -> int:
        return sum([build_step.unit_type_id == unit_type for build_step in self.started])

    def get_queued_count(self, unit_type: UnitTypeId, queue: List[BuildStep]) -> int:
        return sum([build_step.unit_type_id == unit_type for build_step in queue])

    def queue_command_center(self, rush_detected: bool) -> None:
        self.start_timer("queue_command_center")
        if not rush_detected and self.bot.time > 100 or self.bot.time > 300:
            projected_worker_capacity = self.workers.get_mineral_capacity()
            for build_step in self.started + self.static_queue + self.priority_queue:
                if build_step.unit_type_id == UnitTypeId.COMMANDCENTER:
                    projected_worker_capacity += 16

            # adds number of townhalls to account for near-term production
            projected_worker_count = min(self.workers.max_workers, len(self.workers.assignments_by_job[JobType.MINERALS]) + len(self.bot.townhalls.ready) * 4)
            surplus_worker_count = projected_worker_count - projected_worker_capacity
            
            cc_count = self.get_in_progress_count(UnitTypeId.COMMANDCENTER) + self.get_queued_count(UnitTypeId.COMMANDCENTER, self.static_queue)
            needed_cc_count = math.ceil(surplus_worker_count / 16)

            logger.debug(f"expansion: {surplus_worker_count} surplus workers need {needed_cc_count} cc(s)")
            # expand if running out of room for workers at current bases
            if needed_cc_count > cc_count:
                logger.debug("queuing command center")
                self.add_to_build_queue([UnitTypeId.COMMANDCENTER for x in range(needed_cc_count - cc_count)], queue=self.priority_queue)
        self.stop_timer("queue_command_center")

    def queue_refinery(self) -> None:
        self.start_timer("queue_refinery")
        refinery_count = len(self.bot.gas_buildings.ready) + self.get_in_progress_count(UnitTypeId.REFINERY) + self.get_queued_count(UnitTypeId.REFINERY, self.static_queue)
        # build refinery if less than 2 per town hall (function is only called if gas is needed but no room to move workers)
        logger.debug(f"refineries: {refinery_count}, townhalls: {len(self.bot.townhalls)}")
        if self.bot.townhalls.ready:
            geysirs = self.bot.vespene_geyser.in_distance_of_group(
                distance=10, other_units=self.bot.townhalls.ready
            )
            if refinery_count < len(geysirs):
                logger.debug("adding refinery to build order")
                self.add_to_build_queue(UnitTypeId.REFINERY, queue=self.priority_queue)
        # should also build a new one if current bases run out of resources
        self.stop_timer("queue_refinery")

    def queue_production(self) -> None:
        self.start_timer("queue_production")
        # add more barracks/factories/starports to handle backlog of pending affordable units
        self.start_timer("queue_production-get_affordable_build_list")
        affordable_units: List[UnitTypeId] = self.get_affordable_build_list()
        if len(affordable_units) == 0 and self.unit_queue and len(self.static_queue) < 4:
            affordable_units.append(self.unit_queue[0].unit_type_id)
        self.stop_timer("queue_production-get_affordable_build_list")
        self.start_timer("queue_production-additional_needed_production")
        extra_production: List[UnitTypeId] = self.production.additional_needed_production(affordable_units)
        # only add if not already in progress
        extra_production = self.remove_in_progress_from_list(extra_production)
        self.stop_timer("queue_production-additional_needed_production")
        self.start_timer("queue_production-add_to_build_order")
        self.add_to_build_queue(extra_production, position=0, queue=self.static_queue)
        self.stop_timer("queue_production-add_to_build_order")
        self.stop_timer("queue_production")

    def remove_in_progress_from_list(self, build_list: List[UnitTypeId]) -> List[UnitTypeId]:
        in_progress_counts: Dict[UnitTypeId, int] = {}
        result: List[UnitTypeId] = []
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
    def queue_upgrade(self) -> None:
        self.start_timer("queue_upgrade")
        if self.bot.time > 360:
            for facility_type in self.upgrade_building_types:
                if self.bot.structures(facility_type).ready.idle:
                    next_upgrade = self.upgrades.next_upgrade(facility_type)
                    if next_upgrade and not self.upgrade_is_in_progress(next_upgrade):
                        self.add_to_build_queue([next_upgrade], queue=self.priority_queue)
                elif not self.bot.structures(facility_type) and self.get_in_progress_count(facility_type) == 0:
                    new_build_steps = self.production.build_order_with_prereqs(facility_type)
                    new_build_steps = self.remove_in_progress_from_list(new_build_steps)
                    self.add_to_build_queue(new_build_steps, queue=self.static_queue)
            # next_upgrades: List[UpgradeId] = self.upgrades.get_upgrades()
            # for next_upgrade in next_upgrades:
            #     for build_step in self.started:
            #         if next_upgrade == build_step.upgrade_id:
            #             logger.debug(f"upgrade {next_upgrade} already in build order, progress: {self.bot.already_pending_upgrade(build_step.upgrade_id)}")
            #             break
            #     else:
            #         # not already started or pending
            #         logger.debug(f"adding upgrade {next_upgrade} to build order")
            #         self.add_to_build_queue(self.production.build_order_with_prereqs(next_upgrade))
            #         # self.add_to_build_order(self.production.build_order_with_prereqs(next_upgrade), 1)
        self.stop_timer("queue_upgrade")

    def upgrade_is_in_progress(self, upgrade_type: UpgradeId) -> bool:
        for build_step in self.started:
            if build_step.upgrade_id == upgrade_type:
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
            turret_count = len(self.bot.structures.of_type(UnitTypeId.MISSILETURRET).ready) + self.get_in_progress_count(UnitTypeId.MISSILETURRET)
            base_count = len(self.bot.structures.of_type({UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS}))
            if turret_count < base_count:
                self.add_to_build_queue(self.production.build_order_with_prereqs(UnitTypeId.MISSILETURRET))
        self.stop_timer("queue_turret")

    def add_to_build_queue(self, unit_types: Union[UnitTypeId, List[UnitTypeId]], position=None, queue: List[BuildStep] = None) -> None:
        if isinstance(unit_types, UnitTypeId):
            unit_types = [unit_types]
        if queue is None:
            queue = self.build_queue
        for build_step in queue:
            # for build_item in unit_types:
            if build_step.unit_type_id in unit_types:
                unit_types.remove(build_step.unit_type_id)
            elif build_step.upgrade_id in unit_types:
                unit_types.remove(build_step.upgrade_id)
                # in_progress.remove(build_step)
        steps_to_add: List[BuildStep] = [self.create_build_step(unit_type) for unit_type in unit_types]
        if steps_to_add:
            if position is not None:
                steps_to_add = queue[:position] + steps_to_add + queue[position:]
                queue.clear()
            queue.extend(steps_to_add)

    def create_build_step(self, unit_type: UnitTypeId) -> BuildStep:
        return BuildStep(unit_type, self.bot, self.workers, self.production, self.map)

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

    def get_affordable_build_list(self) -> List[UnitTypeId]:
        affordable_items: List[UnitTypeId] = []
        needed_resources: Cost = Cost(-self.bot.minerals, -self.bot.vespene)

        # find first shortage, unit_queue hasn't been added to build_queue yet
        for build_step in self.priority_queue + self.static_queue + self.build_queue + self.unit_queue:
            if not self.subtract_and_can_afford(needed_resources, build_step.cost):
                break
            if build_step.unit_type_id:
                affordable_items.append(build_step.unit_type_id)
            elif build_step.upgrade_id:
                affordable_items.append(build_step.upgrade_id)
        logger.debug(f"affordable items {affordable_items}")
        return affordable_items

    def subtract_and_can_afford(self, needed_resources: Cost, step_cost: Cost) -> bool:
        needed_resources.minerals += step_cost.minerals
        needed_resources.vespene += step_cost.vespene
        return needed_resources.minerals <= 0 and needed_resources.vespene <= 0

    def update_completed_unit(self, completed_unit: Unit) -> None:
        logger.debug(
            f"construction of {completed_unit.type_id} completed at {completed_unit.position}"
        )
        for idx, in_progress_step in enumerate(self.started):
            logger.debug(
                f"{in_progress_step.unit_type_id}, {completed_unit.type_id}"
            )
            if in_progress_step.unit_type_id == completed_unit.type_id:
                if completed_unit.is_structure:
                    if in_progress_step.position.manhattan_distance(completed_unit.position) > 2:
                        # not the same building
                        continue
                elif in_progress_step.unit_in_charge is None:
                    # not sure if/how we get here
                    continue
                in_progress_step.completed_time = self.bot.time
                if in_progress_step.unit_in_charge.type_id == UnitTypeId.SCV:
                    self.workers.set_as_idle(in_progress_step.unit_in_charge)
                self.move_to_complete(self.started.pop(idx))
                break

    def move_to_complete(self, build_step: BuildStep) -> None:
        self.complete.append(build_step)
        for timer_name in build_step.timers.keys():
            if timer_name not in self.timers:
                self.timers[timer_name] = build_step.timers[timer_name]
            else:
                self.timers[timer_name]['total'] += build_step.timers[timer_name]['total']
                logger.debug(f"adding to existing timer for {timer_name}={self.timers[timer_name]['total']}")

    def update_started_structure(self, started_structure: Unit) -> None:
        logger.debug(
            f"construction of {started_structure.type_id} started at {started_structure.position}"
        )
        for in_progress_step in self.started:
            if isinstance(in_progress_step.unit_being_built, Unit):
                continue
            logger.debug(f"{in_progress_step.unit_type_id} {started_structure.type_id}")
            if in_progress_step.unit_type_id == started_structure.type_id or (in_progress_step.unit_type_id == UnitTypeId.REFINERY and started_structure.type_id == UnitTypeId.REFINERYRICH):
                if in_progress_step.unit_in_charge and in_progress_step.unit_in_charge.type_id == UnitTypeId.SCV:
                    try:
                        in_progress_step.unit_in_charge = self.get_updated_unit_reference(in_progress_step.unit_in_charge)
                    except KeyError:
                        continue
                    if not in_progress_step.unit_in_charge.is_constructing_scv:
                        # wrong worker
                        continue
                    self.workers.update_assigment(in_progress_step.unit_in_charge, JobType.BUILD, started_structure)
                logger.debug(f"found matching step: {in_progress_step}")
                in_progress_step.unit_being_built = started_structure
                in_progress_step.position = started_structure.position
                break
        # see if this is a ramp blocker
        ramp_blocker: SpecialLocation
        for ramp_blocker in self.special_locations.ramp_blockers:
            if ramp_blocker == started_structure:
                logger.debug(">> is ramp blocker")
                ramp_blocker.unit_tag = started_structure.tag
                ramp_blocker.is_started = True

    def update_completed_structure(self, completed_structure: Unit) -> None:
        if completed_structure.type_id == UnitTypeId.AUTOTURRET:
            return
        logger.debug(
            f"construction of {completed_structure.type_id} completed at {completed_structure.position}"
        )
        for idx, in_progress_step in enumerate(self.started):
            logger.debug(
                f"{in_progress_step.unit_type_id}, {completed_structure.type_id}"
            )
            structure: Union[bool, Unit] = in_progress_step.unit_being_built
            builder: Unit = in_progress_step.unit_in_charge
            logger.debug(f"type {in_progress_step.unit_type_id}, structure {structure}, upgrade {in_progress_step.upgrade_id}, builder {builder}, pos {in_progress_step.position}")
            is_same_structure = isinstance(structure, Unit) and structure.tag == completed_structure.tag
            if is_same_structure or in_progress_step.position and self.bot.distance_math_hypot_squared(completed_structure.position, in_progress_step.position) < 2.25: # 1.5 squared
                in_progress_step.completed_time = self.bot.time
                if builder.type_id == UnitTypeId.SCV:
                    if in_progress_step.unit_type_id == UnitTypeId.REFINERY:
                        self.workers.vespene.add_node(completed_structure)
                        self.workers.update_assigment(in_progress_step.unit_in_charge, JobType.VESPENE, completed_structure)
                    else:
                        self.workers.set_as_idle(builder)
                self.move_to_complete(self.started.pop(idx))
                break
        ramp_blocker: SpecialLocation
        for ramp_blocker in self.special_locations.ramp_blockers:
            if ramp_blocker == completed_structure:
                logger.debug(">> is ramp blocker")
                ramp_blocker.unit_tag = completed_structure.tag
                ramp_blocker.is_complete = True

    def update_completed_upgrade(self, upgrade: UpgradeId):
        for idx, in_progress_step in enumerate(self.started):
            if in_progress_step.upgrade_id == upgrade:
                logger.debug(
                    f"upgrade {upgrade} completed by {in_progress_step.unit_in_charge}"
                )
                self.move_to_complete(self.started.pop(idx))
                break

    def cancel_damaged_structure(self, unit: Unit, total_damage_amount: float):
        if unit.health_percentage > 0.05:
            return
        for idx, build_step in enumerate(self.all_steps):
            if build_step.unit_being_built is not None and build_step.unit_being_built is not True and build_step.unit_being_built.tag == unit.tag:
                build_step.cancel_construction()
                break

    async def execute_pending_builds(self, only_build_units: bool, rush_detected: bool) -> None:
        self.start_timer("execute_pending_builds")
        remaining_resources: Cost = await self.build_from_queue(self.priority_queue, only_build_units, allow_skip=(self.bot.time > 60), rush_detected=rush_detected)
        if remaining_resources.minerals > 0:
            remaining_resources = await self.build_from_queue(self.static_queue, only_build_units, allow_skip=True, rush_detected=rush_detected, remaining_resources=remaining_resources)
        if remaining_resources.minerals > 0:
            # randomize unit queue so it doesn't get stuck on one unit type
            self.build_queue.sort(key=lambda step: random.randint(0,255), reverse=True)
            await self.build_from_queue(self.build_queue, only_build_units, rush_detected=rush_detected, remaining_resources=remaining_resources)
        self.stop_timer("execute_pending_builds")

    async def build_from_queue(self, build_queue: List[BuildStep], only_build_units: bool = False, allow_skip: bool = True, rush_detected: bool = False, remaining_resources: Cost = None) -> Cost:
        build_response = ResponseCode.QUEUE_EMPTY
        execution_index = -1
        failed_types: list[UnitTypeId] = []
        if remaining_resources is None:
            remaining_resources = Cost(self.bot.minerals, self.bot.vespene)
        build_no_supply_only = False
        while execution_index < len(build_queue):
            execution_index += 1
            try:
                build_step = build_queue[execution_index]
            except IndexError:
                break
            if build_step.supply_cost > 0 and build_no_supply_only:
                continue
            percent_affordable = 1.0
            if build_step.unit_type_id in failed_types or only_build_units and UnitTypeId.SCV in build_step.builder_type:
                continue
            if not build_step.is_in_progress:
                percent_affordable = self.percent_affordable(remaining_resources, build_step.cost)
                if remaining_resources.minerals < 0:
                    break
                remaining_resources = remaining_resources - build_step.cost
            time_since_last_cancel = self.bot.time - build_step.last_cancel_time
            if time_since_last_cancel < 10:
                # delay rebuilding canceled structures
                continue
            if percent_affordable < 1.0:
                build_response = ResponseCode.NO_RESOURCES
                if percent_affordable >= 0.75 and self.bot.tech_requirement_progress(build_step.unit_type_id) == 1.0:
                    await build_step.position_worker(special_locations=self.special_locations, rush_detected=rush_detected)
                continue
            if self.bot.supply_left < build_step.supply_cost and build_step.supply_cost > 0:
                build_no_supply_only = True
                build_response = ResponseCode.NO_SUPPLY
                continue

            # XXX slightly slow
            self.start_timer("build_step.execute")
            build_response = await build_step.execute(special_locations=self.special_locations, rush_defense_enacted=self.rush_defense_enacted)
            self.stop_timer("build_step.execute")
            self.start_timer(f"handle response {build_response}")
            logger.debug(f"building {build_step}, response: {build_response}")
            if build_response == ResponseCode.SUCCESS:
                self.started.append(build_queue.pop(execution_index))
                if build_step.interrupted_count > 5:
                    # can't trust that this actually got built
                    continue
                remaining_resources.minerals = 0
                break
            else:
                if not allow_skip:
                    break
                if build_response == ResponseCode.NO_LOCATION:
                    continue
                elif build_response == ResponseCode.NO_FACILITY:
                    # don't reserve resources for things that don't have an available facility
                    remaining_resources = remaining_resources + build_step.cost
                    failed_types.append(build_step.unit_type_id)
                else:
                    failed_types.append(build_step.unit_type_id)
            self.stop_timer(f"handle response {build_response}")
        self.stop_timer("execute_pending_builds")
        return remaining_resources

    def can_afford(self, remaining_resources: Cost, requested_cost: Cost) -> bool:
        return (
            requested_cost.minerals <= remaining_resources.minerals
            and requested_cost.vespene <= remaining_resources.vespene
        )
    
    def get_blueprints(self) -> List[BuildStep]:
        return [step for step in self.started if step.position is not None and (step.unit_being_built is True or step.unit_being_built is None)]
    
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
