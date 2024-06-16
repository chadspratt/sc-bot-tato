from loguru import logger
from typing import List

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.game_data import Cost
from sc2.game_info import Ramp
from sc2.position import Point2
from sc2.constants import TERRAN_TECH_REQUIREMENT
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM

from bottato.build_step import BuildStep
from bottato.economy.workers import Workers


class RampBlocker:
    def __init__(self, unit_type_id: UnitTypeId, position: Point2):
        self.is_started: bool = False
        self.is_complete: bool = False
        self.unit_tag: int | None = None
        self.unit_type_id = unit_type_id
        self.position = position
        logger.info(f"Will build {unit_type_id} at {position} to block ramp")

    def __eq__(self, other):
        return self.unit_type_id == other.type_id and self.position == other.position


class RampBlock:
    def __init__(self, ramp: Ramp):
        self.is_blocked: bool = False
        self.ramps = []
        self.ramp_blockers = []
        self.add_ramp(ramp)

    def add_ramp(self, ramp: Ramp):
        ramp_blockers: list[RampBlocker] = []
        for corner_position in ramp.corner_depots:
            ramp_blockers.append(RampBlocker(UnitTypeId.SUPPLYDEPOT, corner_position))
        ramp_blockers.append(
            RampBlocker(UnitTypeId.BARRACKS, ramp.barracks_correct_placement)
        )
        self.ramp_blockers.extend(ramp_blockers)

    def find_placement(self, unit_type_id: UnitTypeId) -> Point2:
        for ramp_blocker in self.ramp_blockers:
            if ramp_blocker.is_started:
                continue
            if unit_type_id == ramp_blocker.unit_type_id:
                return ramp_blocker.position
        return None


class BuildOrder:
    pending: List[BuildStep] = []
    started: List[BuildStep] = []
    complete: List[BuildStep] = []
    # next_unfinished_step_index: int
    last_build_position: Point2 = None

    def __init__(self, build_name: str, bot: BotAI, workers: Workers):
        self.recently_completed_units: List[Unit] = []
        # self.recently_completed_transformations: List[UnitTypeId] = []
        self.recently_started_units: List[Unit] = []
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.pending = [
            # BuildStep(unit, bot, workers) for unit in self.get_build_start(build_name)
        ]
        self.ramp_block = RampBlock(ramp=self.bot.main_base_ramp)
        logger.info(f"Starting position: {self.bot.start_location}")

    def update_references(self) -> None:
        logger.info(
            f"pending={','.join([step.unit_type_id.name for step in self.pending])}"
        )
        logger.info(
            f"requested={','.join([step.unit_type_id.name for step in self.started])}"
        )
        self.refresh_worker_references()
        self.update_completed()
        self.update_started()
        self.move_interupted_to_pending()

    async def execute(self):
        self.queue_command_center()
        self.queue_supply()
        self.queue_worker()
        needed_resources: Cost = self.get_first_resource_shortage()
        moved_workers = await self.workers.redistribute_workers(needed_resources)
        logger.info(f"needed gas {needed_resources.vespene}, minerals {needed_resources.minerals}, moved workers {moved_workers}")
        if needed_resources.vespene > 0 and moved_workers == 0:
            self.queue_refinery()
        await self.execute_first_pending()

    def queue_worker(self) -> None:
        requested_worker_count = 0
        for build_step in self.started + self.pending:
            if build_step.unit_type_id == UnitTypeId.SCV:
                requested_worker_count += 1
        worker_build_capacity: int = len(self.bot.townhalls)
        desired_worker_count = worker_build_capacity * 14
        logger.debug(f"requested_worker_count={requested_worker_count}")
        logger.debug(f"worker_build_capacity={worker_build_capacity}")
        if (
            requested_worker_count < worker_build_capacity
            and requested_worker_count + len(self.bot.workers) < desired_worker_count
        ):
            self.pending.insert(1, BuildStep(UnitTypeId.SCV, self.bot, self.workers))

    def queue_command_center(self) -> None:
        requested_worker_count = 0
        for build_step in self.started + self.pending:
            if build_step.unit_type_id == UnitTypeId.SCV:
                requested_worker_count += 1
            elif build_step.unit_type_id == UnitTypeId.COMMANDCENTER:
                return
        # expand if running out of room for workers at current bases
        if (
            requested_worker_count + len(self.bot.workers)
            > len(self.bot.townhalls) * 14 - 4
        ):
            self.pending.insert(1, BuildStep(UnitTypeId.COMMANDCENTER, self.bot, self.workers))
        # should also build a new one if current bases run out of resources

    def queue_refinery(self) -> None:
        refinery_count = len(self.bot.gas_buildings)
        for build_step in self.started + self.pending:
            if build_step.unit_type_id == UnitTypeId.REFINERY:
                refinery_count += 1
        # build refinery if less than 2 per town hall (function is only called if gas is needed but no room to move workers)
        logger.info(f"refineries: {refinery_count}, townhalls: {len(self.bot.townhalls)}")
        if refinery_count < len(self.bot.townhalls) * 2:
            logger.info("adding refinery to build order")
            self.pending.insert(1, BuildStep(UnitTypeId.REFINERY, self.bot, self.workers))
        # should also build a new one if current bases run out of resources

    def queue_supply(self) -> None:
        for build_step in self.started + self.pending:
            if build_step.unit_type_id == UnitTypeId.SUPPLYDEPOT:
                return
        if self.bot.supply_left < 10 and self.bot.supply_cap < 200:
            self.pending.insert(1, BuildStep(UnitTypeId.SUPPLYDEPOT, self.bot, self.workers))

    def queue_military(self, unit_types: list[UnitTypeId]):
        in_progress = self.started + self.pending

        for unit_type in unit_types:
            build_list = self.build_order_with_prereqs(unit_type)
            build_list.reverse()
            logger.info(f"build list with prereqs {build_list}")
            for build_item in build_list:
                for build_step in in_progress:
                    if build_item == build_step.unit_type_id:
                        logger.info(f"already in progress {build_item}")
                        in_progress.remove(build_step)
                        break
                else:
                    # not already started or pending
                    logger.info(f"adding to build order: {build_item}")
                    self.pending.append(BuildStep(build_item, self.bot, self.workers))

    def build_order_with_prereqs(self, unit_type: UnitTypeId) -> list[UnitTypeId]:
        build_order = [unit_type]

        training_facilities = UNIT_TRAINED_FROM[unit_type]
        for training_facility in training_facilities:
            if self.bot.structure_type_build_progress(training_facility) > 0:
                break
            if training_facility == UnitTypeId.SCV:
                # queue workers elsewhere
                break
        else:
            for training_facility in training_facilities:
                # should only be one thing in the set for terran, but won't work for z or p
                build_order.extend(self.build_order_with_prereqs(training_facility))
                break

        if self.bot.tech_requirement_progress(unit_type) == 0:
            build_order.extend(self.build_order_with_prereqs(TERRAN_TECH_REQUIREMENT[unit_type]))

        return build_order

    def get_first_resource_shortage(self) -> Cost:
        needed_resources: Cost = Cost(0, 0)
        if not self.pending:
            return needed_resources

        needed_resources.minerals = -self.bot.minerals
        needed_resources.vespene = -self.bot.vespene

        # find first shortage
        for idx, build_step in enumerate(self.pending):
            needed_resources.minerals += build_step.cost.minerals
            needed_resources.vespene += build_step.cost.vespene
            if needed_resources.minerals > 0 or needed_resources.vespene > 0:
                break
        logger.info(
            f"next {idx + 1} builds "
            f"vespene: {self.bot.vespene}/{needed_resources.vespene + self.bot.vespene}, "
            f"minerals: {self.bot.minerals}/{needed_resources.minerals + self.bot.minerals}"
        )
        return needed_resources

    def update_completed(self) -> None:
        for completed_unit in self.recently_completed_units:
            logger.info(
                f"construction of {completed_unit.type_id} completed at {completed_unit.position}"
            )
            needle = None
            for idx, in_progress_step in enumerate(self.started):
                logger.debug(
                    f"{in_progress_step.unit_type_id}, {completed_unit.type_id}"
                )
                if in_progress_step.unit_type_id == completed_unit.type_id:
                    needle = idx
                    in_progress_step.completed_time = self.bot.time
                    break
            for ramp_blocker in self.ramp_block.ramp_blockers:
                if ramp_blocker == completed_unit:
                    logger.info(">> is ramp blocker")
                    ramp_blocker.tag = completed_unit.tag
                    ramp_blocker.is_complete = True
            if needle is not None:
                self.complete.append(self.started.pop(needle))
            # if completed_unit.type_id == UnitTypeId.COMMANDCENTER:
            #     # generate ramp blocking positions for newly created command centers
            #     # not working... It keeps finding the original ramp location
            #     ramp = min(
            #         (
            #             _ramp
            #             for _ramp in self.bot.game_info.map_ramps
            #             if len(_ramp.upper) in {2, 5}
            #             and _ramp.top_center
            #             not in [r.top_center for r in self.ramp_block.ramps]
            #         ),
            #         key=lambda r: completed_unit.position.distance_to(r.top_center),
            #     )
            #     self.ramp_block.add_ramp(ramp)
        self.recently_completed_units = []

    def update_started(self) -> None:
        logger.debug(
            f"update_started with recently_started_units {self.recently_started_units}"
        )
        for started_unit in self.recently_started_units:
            logger.info(
                f"construction of {started_unit.type_id} started at {started_unit.position}"
            )
            for in_progress_step in self.started:
                if in_progress_step.unit_being_built is not None:
                    continue
                if in_progress_step.unit_type_id == started_unit.type_id:
                    logger.debug(f"found matching step: {in_progress_step}")
                    in_progress_step.unit_being_built = started_unit
                    break
            # see if this is a ramp blocker
            for ramp_blocker in self.ramp_block.ramp_blockers:
                if ramp_blocker == started_unit:
                    logger.info(">> is ramp blocker")
                    ramp_blocker.tag = started_unit.tag
                    ramp_blocker.is_started = True
        self.recently_started_units = []

    def refresh_worker_references(self):
        for build_step in self.started:
            build_step.refresh_worker_reference()

    def move_interupted_to_pending(self) -> None:
        to_promote = []
        for idx, build_step in enumerate(self.started):
            logger.debug(
                f"In progress {build_step.unit_type_id}"
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

    async def execute_first_pending(self) -> None:
        try:
            build_step = self.pending[0]
        except IndexError:
            return False
        if not self.can_afford(build_step.cost):
            logger.debug(f"Cannot afford {build_step.unit_type_id.name}")
            return False
        build_position = await self.find_placement(build_step.unit_type_id)
        logger.debug(f"Executing build step at position {build_position}")
        execute_response = await build_step.execute(at_position=build_position)
        logger.debug(f"> Got back {execute_response}")
        if execute_response:
            self.started.append(self.pending.pop(0))
        else:
            logger.info(f"!!! {build_step.unit_type_id} failed to start building")

    def can_afford(self, requested_cost: Cost) -> bool:
        # PS: non-structure build steps never get their `unit_being_build` populated,
        #   so they inflate the total_requested_cost
        prior_requested_cost = Cost(0, 0)
        for build_step in self.started:
            if build_step.unit_being_built is None:
                logger.debug(
                    f"Build cost for '{build_step.unit_type_id.name}' being added to "
                    "prior_requested_cost"
                )
                prior_requested_cost += build_step.cost
        logger.debug(
            f"Want to buy unit for {requested_cost.minerals} minerals, "
            f"and {requested_cost.vespene} vespene."
        )
        logger.debug(
            f"> Prior (uncharged) requests account for {prior_requested_cost.minerals} minerals, "
            f"and {prior_requested_cost.vespene} vespene."
        )
        logger.debug(
            f">> Currently have {self.bot.minerals} minerals, "
            f"and {self.bot.vespene} vespene."
        )
        total_requested_cost = requested_cost + prior_requested_cost
        return (
            total_requested_cost.minerals <= self.bot.minerals
            and total_requested_cost.vespene <= self.bot.vespene
        )

    async def find_placement(self, unit_type_id: UnitTypeId) -> Point2:
        # depot_position = await self.find_placement(UnitTypeId.SUPPLYDEPOT, near=cc)
        if unit_type_id == UnitTypeId.COMMANDCENTER:
            new_build_position = await self.bot.get_next_expansion()
        else:
            if not self.ramp_block.is_blocked:
                new_build_position = self.ramp_block.find_placement(unit_type_id)
            if new_build_position is None:
                addon_place = False
                if unit_type_id in (
                    UnitTypeId.BARRACKS,
                    UnitTypeId.FACTORY,
                    UnitTypeId.STARPORT,
                ):
                    # account for addon = true
                    addon_place = True
                if self.last_build_position is None:
                    map_center = self.bot.game_info.map_center
                    self.last_build_position = self.bot.start_location.towards(
                        map_center, distance=5
                    )
                new_build_position = await self.bot.find_placement(
                    unit_type_id,
                    near=self.last_build_position,
                    placement_step=2,
                    addon_place=addon_place,
                )
        if new_build_position is not None:
            self.last_build_position = new_build_position
        return new_build_position

    def get_next_build(self) -> List[UnitTypeId]:
        """Figures out what to build next"""
        # or other stuff?
        self.build_steps[self.next_unfinished_step_index]
        return [UnitTypeId.SCV]

    def get_build_start(self, build_name: str) -> list[UnitTypeId]:
        if build_name == "tvt1":
            # https://lotv.spawningtool.com/build/171779/
            # Standard Terran vs Terran (3 Reaper 2 Hellion) (TvT Economic)
            # Very Standard Reaper Hellion Opening that transitions into Marine-Tank-Raven. As solid it as it gets
            return [
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.BARRACKS,
                UnitTypeId.REFINERY,
                UnitTypeId.REFINERY,
                UnitTypeId.REAPER,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.FACTORY,
                UnitTypeId.REAPER,
                UnitTypeId.COMMANDCENTER,
                UnitTypeId.HELLION,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.REAPER,
                UnitTypeId.BARRACKS,
                UnitTypeId.STARPORT,
                UnitTypeId.HELLION,
                UnitTypeId.SUPPLYDEPOT,
                UnitTypeId.BARRACKSREACTOR,
                UnitTypeId.REFINERY,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.ORBITALCOMMAND,
                UnitTypeId.CYCLONE,
                UnitTypeId.MARINE,
                UnitTypeId.MARINE,
                UnitTypeId.RAVEN,
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
