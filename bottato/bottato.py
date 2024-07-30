from loguru import logger
import os

from sc2.bot_ai import BotAI
from sc2.data import Result
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

from .build_order import BuildOrder
from .micro.structure_micro import StructureMicro
from .enemy import Enemy
from .economy.workers import Workers
from .economy.production import Production
from .military import Military
from .mixins import TimerMixin


class BotTato(BotAI, TimerMixin):
    async def on_start(self):
        # name clash with BotAI.workers
        self.my_workers: Workers = Workers(self)
        self.enemy: Enemy = Enemy(self)
        self.military: Military = Military(self, self.enemy)
        self.structure_micro: StructureMicro = StructureMicro(self)
        self.production: Production = Production(self)
        self.build_order: BuildOrder = BuildOrder(
            "tvt1", bot=self, workers=self.my_workers, production=self.production
        )
        # await self.client.debug_fast_build()
        # await self.client.debug_gas()
        # await self.client.debug_minerals()
        # self.client.save_replay_path = "..\replays\bottato.mpq"
        self.last_replay_save_time = 0
        self.last_timer_print = 0
        logger.info(os.getcwd())

    async def on_step(self, iteration):
        logger.info(f"======starting step {iteration} ({self.time}s)======")
        # await self.save_replay()

        self.start_timer("update_unit_references")
        # XXX very slow
        self.update_unit_references()
        self.stop_timer("update_unit_references")
        self.my_workers.distribute_idle()

        self.start_timer("military.manage_squads")
        # XXX extremely slow
        await self.military.manage_squads(iteration)
        self.stop_timer("military.manage_squads")
        self.start_timer("military.get_squad_request")
        # squads_to_fill: List[BaseSquad] = [self.military.get_squad_request()]
        remaining_cap = self.build_order.remaining_cap
        if remaining_cap:
            logger.info(f"requesting at least {remaining_cap} supply of units for military")
            unit_request: list[UnitTypeId] = self.military.get_squad_request(remaining_cap)
            self.stop_timer("military.get_squad_request")
            self.start_timer("build_order.queue_military")
            self.build_order.add_to_build_order(unit_request)
            self.stop_timer("build_order.queue_military")

        self.start_timer("structure_micro.execute")
        await self.structure_micro.execute()
        self.stop_timer("structure_micro.execute")

        self.start_timer("build_order.execute")
        # XXX slow
        await self.build_order.execute()
        self.stop_timer("build_order.execute")
        self.print_all_timers(30)

    async def on_end(self, game_result: Result):
        print("Game ended.")
        self.print_all_timers()
        try:
            logger.info(self.build_order.complete)
        except AttributeError:
            pass

    def update_unit_references(self):
        self.start_timer("my_workers.update_references")
        self.my_workers.update_references()
        self.start_timer("my_workers.update_references")
        self.start_timer("military.update_references")
        self.military.update_references()
        self.start_timer("military.update_references")
        self.start_timer("enemy.update_references")
        self.enemy.update_references()
        self.start_timer("enemy.update_references")
        self.start_timer("build_order.update_references")
        self.build_order.update_references()
        self.start_timer("build_order.update_references")
        self.start_timer("production.update_references")
        self.production.update_references()
        self.start_timer("production.update_references")

    def print_all_timers(self, interval: int = 0):
        if self.time - self.last_timer_print > interval:
            self.last_timer_print = self.time
            self.print_timers("main-")
            self.build_order.print_timers("build_order-")

    async def save_replay(self):
        if self.time - self.last_replay_save_time > 30:
            await self.client.save_replay(".\\replays\\bottato.sc2replay")

        if len(self.units) == 0 or len(self.townhalls) == 0:
            await self.client.save_replay(".\\replays\\bottato.sc2replay")
            await self.client.leave()

    async def on_building_construction_started(self, unit: Unit):
        logger.info(f"building started! {unit}")
        self.build_order.recently_started_units.append(unit)

    async def on_building_construction_complete(self, unit: Unit):
        logger.info(f"building complete! {unit}")
        self.build_order.recently_completed_units.append(unit)
        self.production.add_builder(unit)

    async def on_unit_type_changed(self, unit: Unit, previous_type: UnitTypeId):
        logger.info(f"transformation complete! {previous_type} to {unit.type_id}")
        self.build_order.recently_completed_units.append(unit)

    async def on_unit_created(self, unit: Unit):
        logger.info(f"raising complete! {unit}")
        self.build_order.recently_completed_units.append(unit)
        if unit.type_id not in (UnitTypeId.SCV, UnitTypeId.MULE):
            logger.info(f"assigned to {self.military.main_army.name}")
            self.military.add_to_main(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        logger.info(
            f"Unit taking damage {unit}, "
            f"current health: {unit.health}/{unit.health_max})"
        )
        self.military.report_damage(unit, amount_damage_taken)

    async def on_unit_destroyed(self, unit_tag: int):
        self.enemy.record_death(unit_tag)
        self.military.record_death(unit_tag)
        self.my_workers.record_death(unit_tag)
        logger.info(f"Unit {unit_tag} destroyed")
