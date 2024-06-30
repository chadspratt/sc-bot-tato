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


class BotTato(BotAI):
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
        logger.info(os.getcwd())

    async def on_step(self, iteration):
        logger.info(f"======starting step {iteration} ({self.time}s)======")
        # await self.save_replay()

        self.update_unit_references()
        self.my_workers.distribute_idle()

        await self.military.manage_squads()
        needed_units: list[UnitTypeId] = self.military.get_squad_request()
        self.build_order.queue_military(needed_units)

        await self.structure_micro.execute()

        await self.build_order.execute()

    async def on_end(self, game_result: Result):
        print("Game ended.")
        try:
            logger.info(self.build_order.complete)
        except AttributeError:
            pass

    def update_unit_references(self):
        self.my_workers.update_references()
        self.military.update_references()
        self.enemy.update_references()
        self.build_order.update_references()
        self.production.update_references()

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
            logger.info(f"assigned to {self.military.unassigned_army.name}")
            self.military.unassigned_army.recruit(unit)

    async def on_unit_took_damage(self, unit: Unit, amount_damage_taken: float):
        logger.info(
            f"Unit taking damage {unit}, "
            f"current health: {unit.health}/{unit.health_max})"
        )
        self.military.report_damage(unit, amount_damage_taken)

    async def on_unit_destroyed(self, unit_tag: int):
        self.enemy.record_death(unit_tag)
        self.military.record_death(unit_tag)
        logger.info(f"Unit {unit_tag} destroyed. Condolences.")
