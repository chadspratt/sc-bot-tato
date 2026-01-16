from typing import Dict
from loguru import logger
import os
import random

from sc2.bot_ai import BotAI
from sc2.data import Result
from sc2.game_data import AbilityData
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit

from bottato.commander import Commander
from bottato.enums import ActionErrorCode
from bottato.log_helper import LogHelper
from bottato.mixins import print_decorator_timers, timed_async
from bottato.unit_reference_helper import UnitReferenceHelper


class BotTato(BotAI):
    @timed_async
    async def on_start(self):
        # self.disable_logging()
        self.last_timer_print = 0
        self.last_build_order_print = 0
        self.units_by_tag: Dict[int, Unit] = {}
        self.commander = Commander(self)
        await self.commander.init_map()
        # await self.client.debug_fast_build()
        # await self.client.debug_minerals()
        # await self.client.debug_create_unit(
        #     [
        #         [UnitTypeId.CARRIER, 1, self.game_info.map_center, 2],
        #     ]
        # )
        self.replay_saved = False
        logger.debug(os.getcwd())
        logger.debug(f"vision blockers: {self.game_info.vision_blockers}")
        logger.debug(f"destructibles: {self.destructables}")
        self.draw_map = False
        self.patch_game_data()
        LogHelper.init(self)
        UnitReferenceHelper.init(self, self.units_by_tag)

    @timed_async
    async def on_step(self, iteration: int):
        logger.debug(f"======starting step {iteration} ({self.time}s)======")

        for action_error in self.state.action_errors:
            try:
                LogHelper.add_log(f"Action error: unit={self.all_own_units.by_tag(action_error.unit_tag)}, " +
                                f"ability={action_error.exact_id}, error={ActionErrorCode(action_error.result)}")
                if action_error.result == ActionErrorCode.CantBuildOnThat.value:
                    self.commander.build_order.mark_position_invalid_by_worker_tag(action_error.unit_tag)
            except Exception as e:
                LogHelper.add_log(f"Error processing action error: {e}")
        # XXX very slow
        await self.update_unit_references()

        await self.commander.command(iteration)

        # self.print_all_timers(30)
        if self.draw_map:
            self.commander.map.draw()
        self.print_build_order(10)
        LogHelper.print_logs()

        if LogHelper.testing and self.time >= 3540 and not self.replay_saved:
            # save replay at 59 minutes
            replay_name = f"replays/timeout-{random.randint(1000, 9999)}.SC2Replay"
            await self.client.save_replay(replay_name)
            self.replay_saved = True

    def toggle_map_drawing(self):
        self.draw_map = not self.draw_map

    async def on_end(self, game_result: Result):
        print("Game ended.")
        self.print_all_timers()
        LogHelper.print_logs()
        logger.info(f"Game length: {self.time_formatted}")
        LogHelper.update_match_duration(int(self.time))
        try:
            logger.debug(self.commander.build_order.complete)
        except AttributeError:
            pass

    @timed_async
    async def update_unit_references(self):
        UnitReferenceHelper.update()
        await self.commander.update_references()

    def print_all_timers(self, interval: int = 0):
        if self.time - self.last_timer_print > interval:
            self.last_timer_print = self.time
            if not LogHelper.testing:
                print_decorator_timers()
            LogHelper.add_log(self.commander.build_order.get_build_queue_string())
            LogHelper.add_log(f"upgrades: {self.state.upgrades}")

    def print_build_order(self, interval: int = 0):
        if self.time - self.last_build_order_print > interval:
            self.last_build_order_print = self.time
            LogHelper.add_log(self.commander.military.status_message)
            LogHelper.add_log(f"{self.commander.build_order.get_build_queue_string()}")

    def disable_logging(self):
        logger.disable("bottato")

    async def on_building_construction_started(self, unit: Unit):
        logger.debug(f"building started {unit}")
        self.commander.update_started_structure(unit)

    async def on_building_construction_complete(self, unit: Unit):
        logger.debug(f"building complete {unit}")
        self.commander.update_completed_structure(unit)

    states_to_ignore = {UnitTypeId.SUPPLYDEPOTLOWERED, UnitTypeId.BARRACKSFLYING, UnitTypeId.FACTORYFLYING, UnitTypeId.STARPORTFLYING, UnitTypeId.COMMANDCENTERFLYING, UnitTypeId.ORBITALCOMMANDFLYING}

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        logger.debug(f"transformation complete {previous_type} to {unit.type_id}")

        if unit.is_structure and unit.type_id not in self.states_to_ignore and previous_type not in self.states_to_ignore:
            self.commander.update_completed_structure(unit)

    async def on_unit_created(self, unit: Unit):
        logger.debug(f"unit created {unit}")
        self.commander.add_unit(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        logger.debug(
            f"Unit took {amount_damage_taken} damage {unit}, "
            f"current health: {unit.health}/{unit.health_max})"
        )
        self.commander.log_damage(unit, amount_damage_taken)

    async def on_unit_destroyed(self, unit_tag: int):
        logger.debug(f"Unit {unit_tag} destroyed")
        self.commander.remove_destroyed_unit(unit_tag)

    async def on_upgrade_complete(self, upgrade: UpgradeId):
        logger.debug(f"upgrade completed {upgrade}")
        self.commander.add_upgrade(upgrade)

    def patch_game_data(self):
        # Patch game data here if needed
        class Proto:
            def __init__(self, ability_id: int):
                self.ability_id = ability_id
                self.remaps_to_ability_id = None
        class PatchedId(AbilityData):
            def __init__(self, ability_id: int):
                self._proto = Proto(ability_id)
                # self.button_name = 'Stop'
                # self.cost = Cost(0, 0)
                # self.friendly_name = 'Stop Vespene Gathering'
                # self.is_free_morph = False
                # self.link_name = 'Stop Vespene Gathering'
                # self.description = 'SCV stops gathering vespene gas'
        if 4132 not in self.game_data.abilities:
            self.game_data.abilities[4132] = PatchedId(AbilityId.WORKERSTOPIDLEABILITYVESPENE_GATHER.value)
