from typing import List
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.constants import (
    TERRAN_STRUCTURES_REQUIRE_SCV,
)
from bottato.build_step import BuildStep


class BuildOrder:
    build_steps: List[BuildStep]
    next_unfinished_step_index: int

    def __init__(self, build_name):
        self.next_unfinished_step_index = 0
        self.build_steps = self.get_build_start(build_name)

    def execute(self, bot: BotAI) -> List[BuildStep]:
        failed_steps: List[BuildStep] = []
        step_index = self.next_unfinished_step_index
        self.next_unfinished_step_index = None
        while (self.build_steps[step_index].supply_count <= bot.supply_used):
            next_step: BuildStep = self.build_steps[step_index]
            if (next_step.is_complete(bot)):
                step_index += 1
                continue
            if (self.next_unfinished_step_index is None):
                self.next_unfinished_step_index = step_index
            if (not next_step.execute(bot)):
                failed_steps.append(next_step)
            step_index += 1
        if (self.next_unfinished_step_index is None):
            self.next_unfinished_step_index = step_index
        return failed_steps

    def get_build_start(build_name):
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
