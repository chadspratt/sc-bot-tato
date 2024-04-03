from loguru import logger

from sc2.bot_ai import BotAI
from sc2.data import Result
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.game_data import Cost

from bottato.build_order import BuildOrder
from bottato.micro import Micro
from bottato.enemy import Enemy
from .workers import Workers
from .military import Military


class BotTato(BotAI):
    async def on_start(self):
        # name clash with BotAI.workers
        self._workers: Workers = Workers(self)
        self.military: Military = Military(self)
        self.micro: Micro = Micro(self)
        self.build_order: BuildOrder = BuildOrder(
            "tvt1", bot=self, workers=self._workers
        )
        self.enemy: Enemy = Enemy(self)
        await self.client.debug_fast_build()

    async def on_step(self, iteration):
        logger.info(f"starting step, iteration: {iteration}, time: {self.time}")
        if len(self.units) == 0 or len(self.townhalls) == 0:
            await self.client.leave()

        self.update_unit_references()
        # needed_units: list[UnitTypeId] = self.military.get_units_needed_to_counter(self.enemy)
        # self.build_order.request_military(needed_units)

        await self.micro.execute()
        needed_resources: Cost = self.build_order.get_first_resource_shortage()
        await self._workers.distribute_workers(needed_resources)

        self.military.manage_squads(self.enemy)

        # logger.info("executing build order")
        await self.build_order.execute()
        logger.info("ending step")

    async def on_end(self, game_result: Result):
        print("Game ended.")
        logger.info(self.build_order.complete)
        # Do things here after the game ends

    def update_unit_references(self):
        self._workers.update_references()
        self.military.update_references()
        self.enemy.update_references()

    async def on_building_construction_started(self, unit: Unit):
        logger.info(f"building started! {unit}")
        self.build_order.recently_started_units.append(unit)

    async def on_building_construction_complete(self, unit: Unit):
        logger.info(f"building complete! {unit}")
        self.build_order.recently_completed_units.append(unit)

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

    async def on_unit_destroyed(self, unit_tag: int):
        logger.info(f"Unit {unit_tag} destroyed. Condolences.")
