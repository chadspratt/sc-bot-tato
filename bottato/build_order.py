from loguru import logger
from typing import List

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.game_data import Cost
from sc2.position import Point2

from bottato.build_step import BuildStep
from bottato.workers import Workers


class BuildOrder:
    pending: List[BuildStep] = []
    requested: List[BuildStep] = []
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
            BuildStep(unit, bot, workers) for unit in self.get_build_start(build_name)
        ]

    async def execute(self) -> None:
        logger.info(
            f"pending={','.join([step.unit_type_id.name for step in self.pending])}"
        )
        logger.info(
            f"requested={','.join([step.unit_type_id.name for step in self.requested])}"
        )
        self.queue_worker()
        self.refresh_worker_references()
        self.update_completed()
        self.update_started()
        self.move_interupted_to_pending()
        await self.execute_first_pending()

    def queue_worker(self) -> None:
        requested_worker_count = 0
        for build_step in self.requested + self.pending:
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

    def update_completed(self) -> None:
        for completed_unit in self.recently_completed_units:
            logger.debug(f"update_completed for {completed_unit}")
            needle = None
            for idx, in_progress_step in enumerate(self.requested):
                logger.debug(
                    f"{in_progress_step.unit_type_id}, {completed_unit.type_id}"
                )
                if in_progress_step.unit_type_id == completed_unit.type_id:
                    needle = idx
                    in_progress_step.completed_time = self.bot.time
                    break
            if needle is not None:
                self.complete.append(self.requested.pop(needle))
        self.recently_completed_units = []

    def update_started(self) -> None:
        logger.debug(
            f"update_started with recently_started_units {self.recently_started_units}"
        )
        for started_unit in self.recently_started_units:
            for idx, in_progress_step in enumerate(self.requested):
                if in_progress_step.unit_being_built is not None:
                    continue
                if in_progress_step.unit_type_id == started_unit.type_id:
                    logger.debug(f"found matching step: {in_progress_step}")
                    in_progress_step.unit_being_built = started_unit
                    break
        self.recently_started_units = []

    def refresh_worker_references(self):
        for build_step in self.requested:
            build_step.refresh_worker_reference()

    def move_interupted_to_pending(self) -> None:
        to_promote = []
        for idx, build_step in enumerate(self.requested):
            logger.debug(f"In progress building {build_step.unit_type_id}")
            logger.debug(f"> Builder {build_step.unit_in_charge}")
            build_step.draw_debug_box()
            if build_step.is_interrupted():
                logger.debug("! Is interrupted!")
                # move back to pending (demote)
                to_promote.append(idx)
                continue
        for idx in reversed(to_promote):
            self.pending.insert(0, self.requested.pop(idx))

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
            self.requested.append(self.pending.pop(0))

    def can_afford(self, requested_cost: Cost) -> bool:
        # PS: non-structure build steps never get their `unit_being_build` populated,
        #   so they inflate the total_requested_cost
        prior_requested_cost = Cost(0, 0)
        for build_step in self.requested:
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
                UnitTypeId.STARPORT,
                UnitTypeId.HELLION,
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
