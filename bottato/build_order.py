from loguru import logger

from typing import List
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.game_data import Cost
from sc2.position import Point2
from bottato.build_step import BuildStep


class BuildOrder:
    pending: List[BuildStep] = []
    requested: List[BuildStep] = []
    complete: List[BuildStep] = []
    # next_unfinished_step_index: int
    last_build_position: Point2 = None

    def __init__(self, build_name: str, bot: BotAI):
        self.recently_completed_units: List[Unit] = []
        # self.recently_completed_transformations: List[UnitTypeId] = []
        self.recently_started_units: List[Unit] = []
        self.bot: BotAI = bot
        self.pending = self.get_build_start(build_name)

    def update_completed(self) -> None:
        for completed_unit in self.recently_completed_units:
            logger.info(f"update_completed for {completed_unit}")
            needle = None
            for idx, in_progress_step in enumerate(self.requested):
                logger.info(
                    f"{in_progress_step.unit_type_id}, {completed_unit.type_id}"
                )
                if in_progress_step.unit_type_id == completed_unit.type_id:
                    needle = idx
                    break
            if needle is not None:
                self.complete.append(self.requested.pop(needle))
        self.recently_completed_units = []

    def update_started(self) -> None:
        for started_unit in self.recently_started_units:
            for idx, in_progress_step in enumerate(self.requested):
                if in_progress_step.unit_being_built is not None:
                    continue
                if in_progress_step.unit_type_id == started_unit.type_id:
                    in_progress_step.unit_being_built = started_unit
                    break
        self.recently_started_units = []

    def move_interupted_to_pending(self) -> None:
        to_promote = []
        for idx, build_step in enumerate(self.requested):
            logger.info(f"In progress building {build_step.unit_type_id}")
            logger.info(f"> Builder {build_step.unit_in_charge}")
            if build_step.is_interrupted():
                logger.info("! Is interrupted!")
                # move back to pending (demote)
                to_promote.append(idx)
        for idx in reversed(to_promote):
            self.pending.insert(0, self.requested.pop(idx))

    async def execute_first_pending(self) -> None:
        try:
            build_step = self.pending[0]
        except IndexError:
            return False
        if not self.can_afford(build_step.cost):
            return False
        build_position = await self.find_placement(build_step.unit_type_id)
        if await build_step.execute(at_position=build_position):
            self.requested.append(self.pending.pop(0))

    def can_afford(self, requested_cost: Cost) -> bool:
        total_requested_cost = requested_cost
        for build_step in self.requested:
            if build_step.unit_being_built is None:
                total_requested_cost += build_step.cost
        return (
            total_requested_cost.minerals <= self.bot.minerals
            and total_requested_cost.vespene <= self.bot.vespene
        )

    async def find_placement(self, unit_type_id: UnitTypeId) -> Point2:
        # depot_position = await self.find_placement(UnitTypeId.SUPPLYDEPOT, near=cc)
        if self.last_build_position is None:
            map_center = self.bot.game_info.map_center
            self.last_build_position = self.bot.start_location.towards(
                map_center, distance=5
            )

        self.last_build_position = await self.bot.find_placement(
            unit_type_id, near=self.last_build_position, placement_step=2
        )
        return self.last_build_position

    def queue_worker(self) -> None:
        requested_worker_count = 0
        for build_step in self.requested + self.pending:
            if build_step.unit_type_id == UnitTypeId.SCV:
                requested_worker_count += 1
        worker_build_capacity: int = len(self.bot.townhalls)
        desired_worker_count = worker_build_capacity * 14
        logger.info(f"requested_worker_count={requested_worker_count}")
        logger.info(f"worker_build_capacity={worker_build_capacity}")
        if (
            requested_worker_count < worker_build_capacity
            and requested_worker_count + len(self.bot.workers) < desired_worker_count
        ):
            self.pending.insert(1, BuildStep(self.bot, UnitTypeId.SCV))

    async def execute(self) -> None:
        logger.info(
            f"pending={','.join([step.unit_type_id.name for step in self.pending])}"
        )
        logger.info(
            f"requested={','.join([step.unit_type_id.name for step in self.requested])}"
        )
        self.queue_worker()
        self.update_completed()
        self.move_interupted_to_pending()
        await self.execute_first_pending()

    def get_next_build(self) -> List[UnitTypeId]:
        """Figures out what to build next"""
        # or other stuff?
        self.build_steps[self.next_unfinished_step_index]
        return [UnitTypeId.SCV]

    def get_build_start(self, build_name: str) -> list[BuildStep]:
        if build_name == "tvt1":
            # https://lotv.spawningtool.com/build/171779/
            # Standard Terran vs Terran (3 Reaper 2 Hellion) (TvT Economic)
            # Very Standard Reaper Hellion Opening that transitions into Marine-Tank-Raven. As solid it as it gets
            return [
                BuildStep(self.bot, UnitTypeId.SUPPLYDEPOT),
                BuildStep(self.bot, UnitTypeId.BARRACKS),
                BuildStep(self.bot, UnitTypeId.REFINERY),
                BuildStep(self.bot, UnitTypeId.REFINERY),
                BuildStep(self.bot, UnitTypeId.REAPER),
                BuildStep(self.bot, UnitTypeId.ORBITALCOMMAND),
                BuildStep(self.bot, UnitTypeId.SUPPLYDEPOT),
                BuildStep(self.bot, UnitTypeId.FACTORY),
                BuildStep(self.bot, UnitTypeId.REAPER),
                BuildStep(self.bot, UnitTypeId.COMMANDCENTER),
                BuildStep(self.bot, UnitTypeId.HELLION),
                BuildStep(self.bot, UnitTypeId.SUPPLYDEPOT),
                BuildStep(self.bot, UnitTypeId.REAPER),
                BuildStep(self.bot, UnitTypeId.STARPORT),
                BuildStep(self.bot, UnitTypeId.HELLION),
                BuildStep(self.bot, UnitTypeId.BARRACKSREACTOR),
                BuildStep(self.bot, UnitTypeId.REFINERY),
                BuildStep(self.bot, UnitTypeId.FACTORYTECHLAB),
                BuildStep(self.bot, UnitTypeId.STARPORTTECHLAB),
                BuildStep(self.bot, UnitTypeId.ORBITALCOMMAND),
                BuildStep(self.bot, UnitTypeId.CYCLONE),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.RAVEN),
                BuildStep(self.bot, UnitTypeId.SUPPLYDEPOT),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.SIEGETANK),
                BuildStep(self.bot, UnitTypeId.SUPPLYDEPOT),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.RAVEN),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.SIEGETANK),
                BuildStep(self.bot, UnitTypeId.MARINE),
                BuildStep(self.bot, UnitTypeId.MARINE),
            ]
