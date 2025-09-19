from loguru import logger
import os

from sc2.bot_ai import BotAI
from sc2.data import Result
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

from bottato.commander import Commander
from bottato.mixins import TimerMixin


class BotTato(BotAI, TimerMixin):
    async def on_start(self):
        self.disable_logging()
        self.last_timer_print = 0
        self.commander = Commander(self)
        await self.commander.map.init_natural_positions()
        # await self.client.debug_fast_build()
        # await self.client.debug_minerals()
        self.last_replay_save_time = 0
        logger.debug(os.getcwd())
        logger.debug(f"vision blockers: {self.game_info.vision_blockers}")
        logger.debug(f"destructibles: {self.destructables}")

    async def on_step(self, iteration):
        logger.debug(f"======starting step {iteration} ({self.time}s)======")

        self.start_timer("update_unit_references")
        # XXX very slow
        await self.update_unit_references()
        self.stop_timer("update_unit_references")

        await self.commander.command(iteration)

        self.print_all_timers(30)
        # self.commander.map.draw()

    async def on_end(self, game_result: Result):
        print("Game ended.")
        self.print_all_timers()
        try:
            logger.debug(self.commander.build_order.complete)
        except AttributeError:
            pass

    async def update_unit_references(self):
        self.start_timer("commander.update_references")
        await self.commander.update_references()
        self.stop_timer("commander.update_references")

    def print_all_timers(self, interval: int = 0):
        if self.time - self.last_timer_print > interval:
            self.last_timer_print = self.time
            self.print_timers("main-")
            self.commander.print_timers()
            logger.debug(f"upgrades: {self.state.upgrades}")

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
