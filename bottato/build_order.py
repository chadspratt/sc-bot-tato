from loguru import logger

from typing import List
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.position import Point2
from bottato.build_step import BuildStep


class BuildOrder:
    pending: List[BuildStep] = []
    requested: List[BuildStep] = []
    complete: List[BuildStep] = []
    # next_unfinished_step_index: int

    def __init__(self, build_name):
        self.pending = self.get_build_start(build_name)
        self.recently_completed_units: List[Unit] = []
        self.recently_started_units: List[Unit] = []
    
    def update_completed(self) -> None:
        for completed_unit in self.recently_completed_units:
            needle = None
            for idx, in_progress_step in enumerate(self.requested):
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

    async def execute_first_pending(self, bot: BotAI) -> None:
        try:
            build_step = self.pending[0]
        except IndexError:
            return False
        build_position = await self.find_placement(build_step.unit_type_id, bot)
        if await build_step.execute(bot, at_position=build_position):
            self.requested.append(self.pending.pop(0))
        
    async def find_placement(
        self, unit_type_id: UnitTypeId, bot: BotAI
    ) -> Point2:
        # depot_position = await self.find_placement(UnitTypeId.SUPPLYDEPOT, near=cc)
        near_position = None
        if self.requested:
            near_position = self.requested[-1].pos
        elif self.complete:
            near_position = self.complete[-1].pos
        else:
            map_center = bot.game_info.map_center
            near_position = bot.start_location.towards(
                map_center, distance=5
            )
        if near_position is None:
            logger.info(self.requested)
            logger.info(self.complete)
        return await bot.find_placement(
            unit_type_id, near=near_position, placement_step=2
        )

    def build_workers(self, bot: BotAI) -> None:
        if (
            bot.can_afford(UnitTypeId.SCV) and bot.supply_left > 0 and bot.supply_workers < 22 and (
                bot.structures(UnitTypeId.BARRACKS).ready.amount < 1 and bot.townhalls(UnitTypeId.COMMANDCENTER).idle
                or bot.townhalls(UnitTypeId.ORBITALCOMMAND).idle
            )
        ):
            for th in bot.townhalls.idle:
                th.train(UnitTypeId.SCV)

    async def execute(self, bot: BotAI) -> None:
        self.build_workers(bot)
        self.update_completed()
        self.move_interupted_to_pending()
        await self.execute_first_pending(bot)

    def get_next_build(self) -> List[UnitTypeId]:
        """Figures out what to build next"""
        # or other stuff?
        self.build_steps[self.next_unfinished_step_index]
        return [UnitTypeId.SCV]

    def get_build_start(self, build_name):
        if (build_name == 'tvt1'):
            # https://lotv.spawningtool.com/build/171779/
            # Standard Terran vs Terran (3 Reaper 2 Hellion) (TvT Economic)
            # Very Standard Reaper Hellion Opening that transitions into Marine-Tank-Raven. As solid it as it gets
            return [
                BuildStep(14, UnitTypeId.SUPPLYDEPOT),
                BuildStep(15, UnitTypeId.BARRACKS),
                BuildStep(16, UnitTypeId.REFINERY),
                BuildStep(16, UnitTypeId.REFINERY),
                BuildStep(19, UnitTypeId.REAPER),
                BuildStep(19, UnitTypeId.ORBITALCOMMAND),
                BuildStep(19, UnitTypeId.SUPPLYDEPOT),
                BuildStep(20, UnitTypeId.FACTORY),
                BuildStep(21, UnitTypeId.REAPER),
                BuildStep(23, UnitTypeId.COMMANDCENTER),
                BuildStep(24, UnitTypeId.HELLION),
                BuildStep(26, UnitTypeId.SUPPLYDEPOT),
                BuildStep(26, UnitTypeId.REAPER),
                BuildStep(28, UnitTypeId.STARPORT),
                BuildStep(29, UnitTypeId.HELLION),
                BuildStep(32, UnitTypeId.BARRACKSREACTOR),
                BuildStep(32, UnitTypeId.REFINERY),
                BuildStep(33, UnitTypeId.FACTORYTECHLAB),
                BuildStep(33, UnitTypeId.STARPORTTECHLAB),
                BuildStep(34, UnitTypeId.ORBITALCOMMAND),
                BuildStep(34, UnitTypeId.CYCLONE),
                BuildStep(38, UnitTypeId.MARINE),
                BuildStep(38, UnitTypeId.MARINE),
                BuildStep(40, UnitTypeId.RAVEN),
                BuildStep(43, UnitTypeId.SUPPLYDEPOT),
                BuildStep(43, UnitTypeId.MARINE),
                BuildStep(43, UnitTypeId.MARINE),
                BuildStep(46, UnitTypeId.SIEGETANK),
                BuildStep(52, UnitTypeId.SUPPLYDEPOT),
                BuildStep(52, UnitTypeId.MARINE),
                BuildStep(52, UnitTypeId.MARINE),
                BuildStep(56, UnitTypeId.RAVEN),
                BuildStep(59, UnitTypeId.MARINE),
                BuildStep(59, UnitTypeId.MARINE),
                BuildStep(59, UnitTypeId.SIEGETANK),
                BuildStep(67, UnitTypeId.MARINE),
                BuildStep(67, UnitTypeId.MARINE),
            ]
