import math
from loguru import logger
from typing import Dict, List, Union

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.game_data import Cost

from .build_step import BuildStep
from .economy.workers import Workers, JobType
from .economy.production import Production
from .mixins import TimerMixin
from .upgrades import Upgrades
from .special_locations import SpecialLocations, SpecialLocation


class BuildOrder(TimerMixin):
    pending: List[BuildStep] = []
    started: List[BuildStep] = []
    complete: List[BuildStep] = []
    # next_unfinished_step_index: int
    tech_tree: Dict[UnitTypeId, List[UnitTypeId]] = {}

    def __init__(self, build_name: str, bot: BotAI, workers: Workers, production: Production):
        self.recently_completed_units: List[Unit] = []
        # self.recently_completed_transformations: List[UnitTypeId] = []
        self.recently_started_units: List[Unit] = []
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.production: Production = production
        self.pending = [
            BuildStep(unit, bot, workers, production) for unit in self.get_build_start(build_name)
        ]
        self.upgrades = Upgrades(bot)
        self.special_locations = SpecialLocations(ramp=self.bot.main_base_ramp)
        self.build_a_worker: BuildStep = None
        logger.info(f"Starting position: {self.bot.start_location}")

    def update_references(self) -> None:
        logger.info(
            f"pending={','.join([step.friendly_name for step in self.pending])}"
        )
        logger.info(
            f"started={','.join([step.friendly_name for step in self.started])}"
        )
        for build_step in self.started:
            build_step.update_references()
            logger.debug(f"started step {build_step}")
        self.move_interupted_to_pending()

    @property
    def remaining_cap(self) -> int:
        remaining = self.bot.supply_left
        for step in self.pending:
            if step.unit_type_id:
                remaining -= self.bot.calculate_supply_cost(step.unit_type_id)
        return remaining

    async def execute(self):
        self.queue_upgrade()
        self.queue_turret()
        self.queue_planetary()
        self.queue_production()
        self.queue_command_center()
        self.queue_supply()

        needed_resources: Cost = self.get_first_resource_shortage()

        self.start_timer("redistribute_workers")
        moved_workers = await self.workers.redistribute_workers(needed_resources)
        self.stop_timer("redistribute_workers")
        logger.info(f"needed gas {needed_resources.vespene}, minerals {needed_resources.minerals}, moved workers {moved_workers}")

        if needed_resources.vespene > 0 and moved_workers == 0:
            self.queue_refinery()

        # queue last so it will be at front of queue
        self.queue_worker()

        await self.execute_first_pending(needed_resources)

    def queue_worker(self) -> None:
        self.start_timer("queue_worker")
        if not self.build_a_worker:
            requested_worker_count = 1 if self.build_a_worker else 0
            worker_build_capacity: int = len(self.bot.townhalls.idle)
            desired_worker_count = self.workers.max_workers
            logger.debug(f"requested_worker_count={requested_worker_count}")
            logger.debug(f"worker_build_capacity={worker_build_capacity}")
            if (
                requested_worker_count < worker_build_capacity
                and requested_worker_count + len(self.workers.assignments_by_worker) < desired_worker_count
            ):
                self.build_a_worker = BuildStep(UnitTypeId.SCV, self.bot, self.workers, self.production)
        self.stop_timer("queue_worker")

    def queue_command_center(self) -> None:
        self.start_timer("queue_command_center")
        worker_count = len(self.bot.workers)
        cc_count = 0
        for build_step in self.started:
            if build_step.unit_type_id == UnitTypeId.SCV:
                worker_count += 1
            elif build_step.unit_type_id == UnitTypeId.COMMANDCENTER:
                cc_count += 1
        # adds number of townhalls to account for near-term production
        surplus_worker_count = worker_count - self.workers.get_mineral_capacity() + len(self.bot.townhalls)
        needed_cc_count = math.ceil(surplus_worker_count / 13)
        logger.info(f"expansion: {surplus_worker_count} surplus workers need {needed_cc_count} cc(s)")
        # expand if running out of room for workers at current bases
        if needed_cc_count > 0:
            for i in range(needed_cc_count - cc_count):
                logger.info("queuing command center")
                self.add_to_build_order(UnitTypeId.COMMANDCENTER, 1)
        self.stop_timer("queue_command_center")

    def queue_refinery(self) -> None:
        self.start_timer("queue_refinery")
        refinery_count = len(self.bot.gas_buildings)
        for build_step in self.started + self.pending:
            if build_step.unit_type_id == UnitTypeId.REFINERY:
                refinery_count += 1
        # build refinery if less than 2 per town hall (function is only called if gas is needed but no room to move workers)
        logger.info(f"refineries: {refinery_count}, townhalls: {len(self.bot.townhalls)}")
        if refinery_count < len(self.bot.townhalls) * 2:
            logger.info("adding refinery to build order")
            self.add_to_build_order(UnitTypeId.REFINERY, 0)
        # should also build a new one if current bases run out of resources
        self.stop_timer("queue_refinery")

    def queue_supply(self) -> None:
        self.start_timer("queue_supply")
        for build_step in self.started + self.pending:
            if build_step.unit_type_id == UnitTypeId.SUPPLYDEPOT:
                break
        else:
            if self.bot.supply_cap == 0 or (self.bot.supply_left / self.bot.supply_cap < 0.3 and self.bot.supply_cap < 200):
                self.add_to_build_order(UnitTypeId.SUPPLYDEPOT, 1)
        self.stop_timer("queue_supply")

    def queue_production(self) -> None:
        self.start_timer("queue_production")
        # add more barracks/factories/starports to handle backlog of pending affordable units
        self.start_timer("queue_production-get_affordable_build_list")
        affordable_units: List[UnitTypeId] = self.get_affordable_build_list()
        self.stop_timer("queue_production-get_affordable_build_list")
        self.start_timer("queue_production-additional_needed_production")
        extra_production: List[UnitTypeId] = self.production.additional_needed_production(affordable_units)
        self.stop_timer("queue_production-additional_needed_production")
        self.start_timer("queue_production-add_to_build_order")
        self.add_to_build_order(extra_production)
        self.stop_timer("queue_production-add_to_build_order")
        self.stop_timer("queue_production")

    def queue_upgrade(self) -> None:
        self.start_timer("queue_upgrade")
        if self.bot.time > 360:
            next_upgrades: List[UpgradeId] = self.upgrades.get_upgrades()
            for next_upgrade in next_upgrades:
                for build_step in self.started + self.pending:
                    if next_upgrade == build_step.upgrade_id:
                        logger.info(f"upgrade {next_upgrade} already in build order, progress: {self.bot.already_pending_upgrade(build_step.upgrade_id)}")
                        break
                else:
                    # not already started or pending
                    logger.info(f"adding upgrade {next_upgrade} to build order")
                    self.add_to_build_order(self.production.build_order_with_prereqs(next_upgrade), 1)
        self.stop_timer("queue_upgrade")

    def queue_planetary(self) -> None:
        self.start_timer("queue_planetary")
        planetary_count = len(self.bot.structures.of_type(UnitTypeId.PLANETARYFORTRESS))
        cc_count = len(self.bot.structures.of_type(UnitTypeId.COMMANDCENTER))
        if planetary_count < cc_count:
            self.add_to_build_order(self.production.build_order_with_prereqs(UnitTypeId.PLANETARYFORTRESS))
        self.stop_timer("queue_planetary")

    def queue_turret(self) -> None:
        self.start_timer("queue_turret")
        if self.bot.time > 300:
            turret_count = len(self.bot.structures.of_type(UnitTypeId.MISSILETURRET))
            base_count = len(self.bot.structures.of_type({UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS}))
            if turret_count < base_count:
                self.add_to_build_order(self.production.build_order_with_prereqs(UnitTypeId.MISSILETURRET))
        self.stop_timer("queue_turret")

    def add_to_build_order(self, unit_types: Union[UnitTypeId, List[UnitTypeId]], position: int = -1) -> None:
        in_progress = self.started + self.pending
        already_in_build_order = []
        added_to_build_order = []
        if isinstance(unit_types, UnitTypeId):
            unit_types = [unit_types]
        for build_item in unit_types:
            for build_step in in_progress:
                if build_item == build_step.unit_type_id or build_item == build_step.upgrade_id:
                    already_in_build_order.append(build_item)
                    in_progress.remove(build_step)
                    break
            else:
                # not already started or pending
                added_to_build_order.append(build_item)
                if position > -1:
                    self.pending.insert(position, BuildStep(build_item, self.bot, self.workers, self.production))
                else:
                    self.pending.append(BuildStep(build_item, self.bot, self.workers, self.production))
        logger.info(f"already in build order {already_in_build_order}")
        logger.info(f"adding to build order: {added_to_build_order}")

    def get_first_resource_shortage(self) -> Cost:
        self.start_timer("get_first_resource_shortage")
        needed_resources: Cost = Cost(-self.bot.minerals, -self.bot.vespene)
        if self.build_a_worker:
            needed_resources.minerals += self.build_a_worker.cost.minerals
            needed_resources.vespene += self.build_a_worker.cost.vespene
        if self.pending:
            # find first shortage
            for idx, build_step in enumerate(self.pending):
                if needed_resources.minerals > 0 or needed_resources.vespene > 0:
                    break
                needed_resources.minerals += build_step.cost.minerals
                needed_resources.vespene += build_step.cost.vespene
            logger.info(
                f"next {idx + 1} builds "
                f"vespene: {self.bot.vespene}/{needed_resources.vespene + self.bot.vespene}, "
                f"minerals: {self.bot.minerals}/{needed_resources.minerals + self.bot.minerals}"
            )
        self.stop_timer("get_first_resource_shortage")
        return needed_resources

    def get_affordable_build_list(self) -> List[UnitTypeId]:
        affordable_items: List[UnitTypeId] = []
        needed_resources: Cost = Cost(-self.bot.minerals, -self.bot.vespene)
        if self.build_a_worker:
            needed_resources.minerals += self.build_a_worker.cost.minerals
            needed_resources.vespene += self.build_a_worker.cost.vespene
            if needed_resources.minerals < 0 and needed_resources.vespene < 0:
                affordable_items.append(self.build_a_worker.unit_type_id)

        # find first shortage
        for idx, build_step in enumerate(self.pending):
            needed_resources.minerals += build_step.cost.minerals
            needed_resources.vespene += build_step.cost.vespene
            if needed_resources.minerals > 0 or needed_resources.vespene > 0:
                break
            if build_step.unit_type_id:
                affordable_items.append(build_step.unit_type_id)
            elif build_step.upgrade_id:
                affordable_items.append(build_step.upgrade_id)
        logger.info(f"affordable items {affordable_items}")
        return affordable_items

    def update_completed_unit(self, completed_unit: Unit) -> None:
        logger.info(
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
                logger.info(f"adding to existing timer for {timer_name}={self.timers[timer_name]['total']}")

    def update_started_structure(self, started_structure: Unit) -> None:
        logger.info(
            f"construction of {started_structure.type_id} started at {started_structure.position}"
        )
        for in_progress_step in self.started:
            if isinstance(in_progress_step.unit_being_built, Unit):
                continue
            logger.info(f"{in_progress_step.unit_type_id} {started_structure.type_id}")
            if in_progress_step.unit_type_id == started_structure.type_id or (in_progress_step.unit_type_id == UnitTypeId.REFINERY and started_structure.type_id == UnitTypeId.REFINERYRICH):
                logger.info(f"found matching step: {in_progress_step}")
                in_progress_step.unit_being_built = started_structure
                in_progress_step.pos = started_structure.position
                if in_progress_step.unit_in_charge.type_id == UnitTypeId.SCV:
                    self.workers.update_target(in_progress_step.unit_in_charge, started_structure)
                break
        # see if this is a ramp blocker
        ramp_blocker: SpecialLocation
        for ramp_blocker in self.special_locations.ramp_blockers:
            if ramp_blocker == started_structure:
                logger.info(">> is ramp blocker")
                ramp_blocker.unit_tag = started_structure.tag
                ramp_blocker.is_started = True

    def update_completed_structure(self, completed_structure: Unit, previous_type: UnitTypeId = UnitTypeId.NOTAUNIT) -> None:
        if completed_structure.type_id == UnitTypeId.AUTOTURRET:
            return
        logger.info(
            f"construction of {completed_structure.type_id} completed at {completed_structure.position}"
        )
        for idx, in_progress_step in enumerate(self.started):
            logger.debug(
                f"{in_progress_step.unit_type_id}, {completed_structure.type_id}"
            )
            structure: Union[bool, Unit] = in_progress_step.unit_being_built
            builder: Unit = in_progress_step.unit_in_charge
            logger.info(f"type {in_progress_step.unit_type_id}, structure {structure}, upgrade {in_progress_step.upgrade_id}, builder {builder}, pos {in_progress_step.pos}")
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
                logger.info(">> is ramp blocker")
                ramp_blocker.unit_tag = completed_structure.tag
                ramp_blocker.is_complete = True

    def update_completed_upgrade(self, upgrade: UpgradeId):
        for idx, in_progress_step in enumerate(self.started):
            if in_progress_step.upgrade_id == upgrade:
                logger.info(
                    f"upgrade {upgrade} completed by {in_progress_step.unit_in_charge}"
                )
                self.move_to_complete(self.started.pop(idx))
                break

    def move_interupted_to_pending(self) -> None:
        to_promote = []
        for idx, build_step in enumerate(self.started):
            logger.info(
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
            self.pending.insert(0, self.started.pop(idx))

    async def execute_first_pending(self, needed_resources: Cost) -> None:
        self.start_timer("execute_first_pending")
        execution_index = -1
        failed_types: list[UnitTypeId] = []
        remaining_resources = Cost(self.bot.minerals, self.bot.vespene)
        if self.build_a_worker:
            build_step = self.build_a_worker
            if self.can_afford(remaining_resources, build_step.cost):
                self.start_timer("build_step.execute")
                build_response = await build_step.execute(special_locations=self.special_locations, needed_resources=needed_resources)
                self.stop_timer("build_step.execute")
                self.start_timer(f"handle response {build_response}")
                logger.info(f"build_response: {build_response}")
                if build_response == build_step.ResponseCode.SUCCESS:
                    self.started.append(build_step)
                    remaining_resources -= build_step.cost
                    self.build_a_worker = None

        while execution_index < len(self.pending):
            execution_index += 1
            try:
                build_step = self.pending[execution_index]
            except IndexError:
                break
            if build_step.unit_type_id in failed_types:
                continue
            if not self.can_afford(remaining_resources, build_step.cost):
                logger.info(f"Cannot afford {build_step.friendly_name}")
                break

            # XXX slightly slow
            self.start_timer("build_step.execute")
            build_response = await build_step.execute(special_locations=self.special_locations, needed_resources=needed_resources)
            self.stop_timer("build_step.execute")
            self.start_timer(f"handle response {build_response}")
            logger.info(f"build_response: {build_response}")
            if build_response == build_step.ResponseCode.SUCCESS:
                self.started.append(self.pending.pop(execution_index))
                break
            elif build_response == build_step.ResponseCode.NO_LOCATION:
                continue
            else:
                failed_types.append(build_step.unit_type_id)
                logger.debug(f"!!! {build_step.unit_type_id} failed to start building, {build_response}")
            self.stop_timer(f"handle response {build_response}")
            logger.debug(f"pending loop: {execution_index} < {len(self.pending)}")
        self.stop_timer("execute_first_pending")

    def can_afford(self, remaining_resources: Cost, requested_cost: Cost) -> bool:
        return (
            requested_cost.minerals <= remaining_resources.minerals
            and requested_cost.vespene <= remaining_resources.vespene
        )

    def get_build_start(self, build_name: str) -> List[UnitTypeId]:
        if build_name == "empty":
            return []
        elif build_name == "test":
            return [
                UnitTypeId.SUPPLYDEPOT,
                # UnitTypeId.BARRACKS,
                UnitTypeId.REFINERY,
                # UnitTypeId.BARRACKSTECHLAB,
                # UpgradeId.SHIELDWALL
            ]
        elif build_name == "tvt1":
            # https://lotv.spawningtool.com/build/171779/
            # Standard Terran vs Terran (3 Reaper 2 Hellion) (TvT Economic)
            # Very Standard Reaper Hellion Opening that transitions into Marine-Tank-Raven. As solid it as it gets
            return [
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.BARRACKS,
                UnitTypeId.REFINERY,
                UnitTypeId.REFINERY,
                UnitTypeId.REAPER,
                UnitTypeId.BARRACKSREACTOR,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.STARPORT,
                UnitTypeId.MEDIVAC,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.FACTORY,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.REAPER,
                UnitTypeId.COMMANDCENTER,
                UnitTypeId.HELLION,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.REAPER,
                UnitTypeId.BARRACKS,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.REFINERY,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.CYCLONE,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.RAVEN,
                UnitTypeId.BANSHEE,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SIEGETANK,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.RAVEN,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.SIEGETANK,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.RAVEN,
            ]
        elif build_name == 'uthermal tvt':
            return [
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.BARRACKS,
                UnitTypeId.REFINERY,
                UnitTypeId.BARRACKSREACTOR,
                UnitTypeId.MARINE,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.REAPER,
                UnitTypeId.REFINERY,
                UnitTypeId.FACTORY,
                UnitTypeId.REAPER,
                UnitTypeId.CYCLONE,
                UnitTypeId.COMMANDCENTER,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.REFINERY,
                UnitTypeId.SIEGETANK,
                UnitTypeId.SIEGETANK,
                UnitTypeId.STARPORT,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.RAVEN,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.COMMANDCENTER,
                UnitTypeId.REFINERY,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.RAVEN,
                UnitTypeId.SIEGETANK,
                UnitTypeId.ENGINEERINGBAY,
                UnitTypeId.RAVEN,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.SIEGETANK,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.ARMORY,
                UnitTypeId.SIEGETANK,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.REFINERY,
                UnitTypeId.REFINERY,
                UnitTypeId.BARRACKSTECHLAB,
                UnitTypeId.FACTORY,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.FACTORY,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.SIEGETANK,
                UnitTypeId.SIEGETANK,
                UnitTypeId.HELLION,
                UnitTypeId.HELLION,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.HELLION,
                UnitTypeId.HELLION,
                UnitTypeId.FACTORY,
                UnitTypeId.FACTORY,
                UnitTypeId.COMMANDCENTER,
            ]
