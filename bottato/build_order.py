import math
from loguru import logger
from typing import Dict, List, Union

from sc2.ids.ability_id import AbilityId
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.game_data import Cost

from bottato.build_step import BuildStep, ResponseCode
from bottato.economy.workers import Workers, JobType
from bottato.economy.production import Production
from bottato.mixins import TimerMixin
from bottato.upgrades import Upgrades
from bottato.special_locations import SpecialLocations, SpecialLocation
from bottato.map.map import Map
from bottato.build_starts import BuildStarts


class BuildOrder(TimerMixin):
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

    def update_references(self) -> None:
        logger.debug(
            f"pending={','.join([step.friendly_name for step in self.static_queue])}"
        )
        logger.debug(
            f"started={','.join([step.friendly_name for step in self.started])}"
        )
        for build_step in self.started:
            build_step.update_references()
            logger.debug(f"started step {build_step}")
        self.move_interupted_to_pending()

    def get_pending_buildings(self):
        buildings = [
            {
                "type_id": p.unit_type_id,
                "position": p.pos
            }
            for p in self.static_queue + self.started if p.pos is not None
        ]
        # if self.supply_build_step is not None and self.supply_build_step.pos is not None:
        #     buildings.append({
        #         "type_id": self.supply_build_step.unit_type_id,
        #         "position": self.supply_build_step.pos
        #     })
        return buildings

    @property
    def remaining_cap(self) -> int:
        remaining = self.bot.supply_left
        # for step in self.pending:
        # for step in self.build_queue:
        #     if step.unit_type_id:
        #         remaining -= self.bot.calculate_supply_cost(step.unit_type_id)
        return remaining

    async def execute(self, army_ratio: float):
        self.build_queue.clear()

        if self.static_queue and self.static_queue[0].unit_type_id in (UnitTypeId.ORBITALCOMMAND, UnitTypeId.SUPPLYDEPOT):
            self.priority_queue.insert(0, self.static_queue.pop(0))

        self.queue_worker()
        self.queue_supply()
        self.queue_upgrade()
        self.queue_turret()
        self.queue_planetary()
        self.queue_command_center()
        self.queue_production()
        self.build_queue.extend(self.unit_queue)

        only_build_units = army_ratio > 0.0 and army_ratio < 0.8

        needed_resources: Cost = self.get_first_resource_shortage(only_build_units)

        self.start_timer("redistribute_workers")
        moved_workers = await self.workers.redistribute_workers(needed_resources)
        self.stop_timer("redistribute_workers")
        logger.debug(f"needed gas {needed_resources.vespene}, minerals {needed_resources.minerals}, moved workers {moved_workers}")

        if needed_resources.vespene > 0 and moved_workers == 0:
            self.queue_refinery()

        build_order_message = f"priority={'\n'.join([step.friendly_name for step in self.priority_queue])}"
        build_order_message += f"\nstatic={'\n'.join([step.friendly_name for step in self.static_queue])}"
        build_order_message += f"\nbuild_queue={'\n'.join([step.friendly_name for step in self.build_queue])}"
        self.bot.client.debug_text_screen(build_order_message, (0.01, 0.1))

        await self.execute_pending_builds(needed_resources, only_build_units)

    def add_to_build_queue(self, unit_types: Union[UnitTypeId, List[UnitTypeId]], position=None, queue: List[BuildStep] = None) -> None:
        if isinstance(unit_types, UnitTypeId):
            unit_types = [unit_types]
        if queue is None:
            queue = self.build_queue
        in_progress = [] + self.started + queue
        steps_to_add = []
        for build_item in unit_types:
            for build_step in in_progress:
                if build_item == build_step.unit_type_id or build_item == build_step.upgrade_id:
                    in_progress.remove(build_step)
                    break
            else:
                steps_to_add.append(self.create_build_step(build_item))
        if steps_to_add:
            if position is not None:
                steps_to_add = queue[:position] + steps_to_add + queue[position:]
                queue.clear()
            queue.extend(steps_to_add)

    def create_build_step(self, unit_type: UnitTypeId) -> BuildStep:
        return BuildStep(unit_type, self.bot, self.workers, self.production, self.map)

    def queue_units(self, unit_types: List[UnitTypeId]) -> None:
        self.unit_queue = [self.create_build_step(unit_type) for unit_type in unit_types]

    def queue_worker(self) -> None:
        self.start_timer("get_queued_worker")
        worker_build_capacity: int = len(self.bot.townhalls.idle)
        desired_worker_count = self.workers.max_workers
        # desired_worker_count = max(30, self.bot.supply_cap / 3)
        logger.debug(f"worker_build_capacity={worker_build_capacity}")
        if (
            worker_build_capacity > 0
            and len(self.workers.assignments_by_worker) < desired_worker_count
        ):
            self.add_to_build_queue(UnitTypeId.SCV, queue=self.priority_queue)
        self.stop_timer("get_queued_worker")

    def queue_supply(self) -> None:
        self.start_timer("queue_supply")
        if self.bot.supply_cap < 200 and UnitTypeId.SUPPLYDEPOT not in self.static_queue:
            if self.bot.supply_cap == 0:
                self.add_to_build_queue(UnitTypeId.SUPPLYDEPOT)
            else:
                supply_percent_remaining = self.bot.supply_left / self.bot.supply_cap
                if supply_percent_remaining <= 0.3:
                    in_progress_supply = 0
                    for build_step in self.started + self.static_queue:
                        if build_step.unit_type_id == UnitTypeId.SUPPLYDEPOT:
                            in_progress_supply += 1
                    new_ids = []
                    if in_progress_supply == 0:
                        new_ids.append(UnitTypeId.SUPPLYDEPOT)
                    if supply_percent_remaining <= 0.2 and in_progress_supply == 1:
                        new_ids.append(UnitTypeId.SUPPLYDEPOT)
                    self.add_to_build_queue(new_ids, queue=self.priority_queue)
        self.stop_timer("queue_supply")

    def queue_command_center(self) -> None:
        self.start_timer("queue_command_center")
        if self.bot.time > 100:
            worker_count = len(self.bot.workers)
            cc_count = 0
            for build_step in self.started + self.static_queue:
                if build_step.unit_type_id == UnitTypeId.SCV:
                    worker_count += 1
                elif build_step.unit_type_id == UnitTypeId.COMMANDCENTER:
                    cc_count += 1
            # adds number of townhalls to account for near-term production
            surplus_worker_count = worker_count - self.workers.get_mineral_capacity() + len(self.bot.townhalls)
            needed_cc_count = math.ceil(surplus_worker_count / 12)
            logger.debug(f"expansion: {surplus_worker_count} surplus workers need {needed_cc_count} cc(s)")
            # expand if running out of room for workers at current bases
            if needed_cc_count > 0:
                for i in range(needed_cc_count - cc_count):
                    logger.debug("queuing command center")
                    self.add_to_build_queue(UnitTypeId.COMMANDCENTER, queue=self.priority_queue)
                    # self.build_queue.append(self.create_build_step(UnitTypeId.COMMANDCENTER))
        self.stop_timer("queue_command_center")

    def queue_refinery(self) -> None:
        self.start_timer("queue_refinery")
        refinery_count = len(self.bot.gas_buildings)
        for build_step in self.started + self.static_queue:
            if build_step.unit_type_id == UnitTypeId.REFINERY:
                refinery_count += 1
        # build refinery if less than 2 per town hall (function is only called if gas is needed but no room to move workers)
        logger.debug(f"refineries: {refinery_count}, townhalls: {len(self.bot.townhalls)}")
        if refinery_count < len(self.bot.townhalls) * 2:
            logger.debug("adding refinery to build order")
            self.add_to_build_queue(UnitTypeId.REFINERY, queue=self.priority_queue)
        # should also build a new one if current bases run out of resources
        self.stop_timer("queue_refinery")

    def queue_production(self) -> None:
        self.start_timer("queue_production")
        # add more barracks/factories/starports to handle backlog of pending affordable units
        self.start_timer("queue_production-get_affordable_build_list")
        affordable_units: List[UnitTypeId] = self.get_affordable_build_list()
        if len(affordable_units) == 0 and self.unit_queue:
            affordable_units.append(self.unit_queue[0].unit_type_id)
        self.stop_timer("queue_production-get_affordable_build_list")
        self.start_timer("queue_production-additional_needed_production")
        extra_production: List[UnitTypeId] = self.production.additional_needed_production(affordable_units)
        self.stop_timer("queue_production-additional_needed_production")
        self.start_timer("queue_production-add_to_build_order")
        self.add_to_build_queue(extra_production, position=0, queue=self.static_queue)
        self.stop_timer("queue_production-add_to_build_order")
        self.stop_timer("queue_production")

    def queue_upgrade(self) -> None:
        self.start_timer("queue_upgrade")
        if self.bot.time > 360:
            next_upgrades: List[UpgradeId] = self.upgrades.get_upgrades()
            for next_upgrade in next_upgrades:
                for build_step in self.started:
                    if next_upgrade == build_step.upgrade_id:
                        logger.debug(f"upgrade {next_upgrade} already in build order, progress: {self.bot.already_pending_upgrade(build_step.upgrade_id)}")
                        break
                else:
                    # not already started or pending
                    logger.debug(f"adding upgrade {next_upgrade} to build order")
                    self.add_to_build_queue(self.production.build_order_with_prereqs(next_upgrade))
                    # self.add_to_build_order(self.production.build_order_with_prereqs(next_upgrade), 1)
        self.stop_timer("queue_upgrade")

    def queue_planetary(self) -> None:
        self.start_timer("queue_planetary")
        planetary_count = len(self.bot.structures.of_type(UnitTypeId.PLANETARYFORTRESS))
        cc_count = len(self.bot.structures.of_type(UnitTypeId.COMMANDCENTER))
        if self.bot.time > 500 and planetary_count < cc_count:
            self.add_to_build_queue(self.production.build_order_with_prereqs(UnitTypeId.PLANETARYFORTRESS))
        self.stop_timer("queue_planetary")

    def queue_turret(self) -> None:
        self.start_timer("queue_turret")
        if self.bot.time > 300:
            turret_count = len(self.bot.structures.of_type(UnitTypeId.MISSILETURRET))
            base_count = len(self.bot.structures.of_type({UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS}))
            if turret_count < base_count:
                self.add_to_build_queue(self.production.build_order_with_prereqs(UnitTypeId.MISSILETURRET))
        self.stop_timer("queue_turret")

    def get_first_resource_shortage(self, only_build_units: bool) -> Cost:
        self.start_timer("get_first_resource_shortage")
        needed_resources: Cost = Cost(-self.bot.minerals, -self.bot.vespene)
        if self.build_queue:
            # find first shortage
            for idx, build_step in enumerate(self.build_queue):
                if only_build_units and build_step.builder_type == UnitTypeId.SCV:
                    continue
                if needed_resources.minerals > 0 or needed_resources.vespene > 0:
                    break
                needed_resources.minerals += build_step.cost.minerals
                needed_resources.vespene += build_step.cost.vespene
        self.stop_timer("get_first_resource_shortage")
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
                logger.debug(f"found matching step: {in_progress_step}")
                in_progress_step.unit_being_built = started_structure
                in_progress_step.pos = started_structure.position
                if in_progress_step.unit_in_charge.type_id == UnitTypeId.SCV:
                    self.workers.update_target(in_progress_step.unit_in_charge, started_structure)
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
            logger.debug(f"type {in_progress_step.unit_type_id}, structure {structure}, upgrade {in_progress_step.upgrade_id}, builder {builder}, pos {in_progress_step.pos}")
            is_same_structure = isinstance(structure, Unit) and structure.tag == completed_structure.tag
            if is_same_structure or in_progress_step.pos and completed_structure.position.distance_to(in_progress_step.pos) < 1.5:
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

    def cancel_damaged_structure(self, unit: Unit, damage_amount: float):
        if unit.health > damage_amount * 2:
            return
        for idx, build_step in enumerate(self.started):
            if build_step.unit_being_built is not None and build_step.unit_being_built is not True and build_step.unit_being_built.tag == unit.tag:
                unit(AbilityId.BUILDINPROGRESSNONCANCELLABLE_CANCEL)
                logger.debug(f"canceling build of {unit}")
                build_step.unit_being_built = None
                build_step.last_cancel = self.bot.time
                if build_step.unit_in_charge.type_id == UnitTypeId.SCV:
                    self.workers.update_assigment(build_step.unit_in_charge, JobType.IDLE, None)
                # self.pending.insert(0, self.started.pop(idx))
                break

    def move_interupted_to_pending(self) -> None:
        to_promote = []
        for idx, build_step in enumerate(self.started):
            logger.debug(
                f"In progress {build_step.unit_type_id} {build_step.upgrade_id}"
                f"> Builder {build_step.unit_in_charge}"
            )
            build_step.draw_debug_box()
            if build_step.is_interrupted():
                logger.debug("! Is interrupted!")
                # move back to pending (demote)
                to_promote.append(idx)
                continue
        for idx in reversed(to_promote):
            self.static_queue.insert(0, self.started.pop(idx))

    async def execute_pending_builds(self, needed_resources: Cost, only_build_units: bool) -> None:
        self.start_timer("execute_pending_builds")
        response = await self.build_from_queue(self.priority_queue, needed_resources, only_build_units)
        if response != ResponseCode.NO_RESOURCES:
            response = await self.build_from_queue(self.static_queue, needed_resources, only_build_units)
        if response != ResponseCode.NO_RESOURCES:
            await self.build_from_queue(self.build_queue, needed_resources, only_build_units)
        self.stop_timer("execute_pending_builds")

    async def build_from_queue(self, build_queue: List[BuildStep], needed_resources: Cost, only_build_units: bool = False) -> ResponseCode:
        build_response = ResponseCode.QUEUE_EMPTY
        execution_index = -1
        failed_types: list[UnitTypeId] = []
        remaining_resources = Cost(self.bot.minerals, self.bot.vespene)
        while execution_index < len(build_queue):
            execution_index += 1
            try:
                build_step = build_queue[execution_index]
            except IndexError:
                break
            if build_step.unit_type_id in failed_types or only_build_units and build_step.builder_type == UnitTypeId.SCV:
                continue
            time_since_last_cancel = self.bot.time - build_step.last_cancel
            if time_since_last_cancel < 5:
                # delay rebuilding canceled structures
                continue
            if not self.can_afford(remaining_resources, build_step.cost):
                logger.debug(f"Cannot afford {build_step.friendly_name}")
                build_response = ResponseCode.NO_RESOURCES
                break

            # XXX slightly slow
            self.start_timer("build_step.execute")
            build_response = await build_step.execute(special_locations=self.special_locations, needed_resources=needed_resources)
            self.stop_timer("build_step.execute")
            self.start_timer(f"handle response {build_response}")
            logger.debug(f"build_response: {build_response}")
            if build_response == ResponseCode.SUCCESS:
                self.started.append(build_queue.pop(execution_index))
                break
            elif build_response == ResponseCode.NO_LOCATION:
                continue
            else:
                failed_types.append(build_step.unit_type_id)
                logger.debug(f"!!! {build_step.unit_type_id} failed to start building, {build_response}")
            self.stop_timer(f"handle response {build_response}")
            logger.debug(f"pending loop: {execution_index} < {len(build_queue)}")
        self.stop_timer("execute_pending_builds")
        return build_response

    def can_afford(self, remaining_resources: Cost, requested_cost: Cost) -> bool:
        return (
            requested_cost.minerals <= remaining_resources.minerals
            and requested_cost.vespene <= remaining_resources.vespene
        )
