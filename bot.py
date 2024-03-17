# import sys
# from datetime import datetime
from loguru import logger

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.data import Result
from sc2.units import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.main import run_game
from sc2.player import Bot, Computer

from bottato.build_order import BuildOrder
from bottato.micro import Micro

# logger.add(f"bot_tato-{datetime.now().timestamp()}.log", level="INFO")
logger.add("bot_tato.log", level="INFO", format="{message}")


class BotTato(BotAI):
    async def on_start(self):
        self.build_order: BuildOrder = BuildOrder('tvt1', bot=self)
        self.micro = Micro(self)
        for cc in self.townhalls(UnitTypeId.COMMANDCENTER):
            logger.info(f"Command center located at {cc.position}")

    async def on_step(self, iteration):
        logger.info("starting step")
        # logger.info("adjust_supply_depots_for_enemies step")
        self.micro.adjust_supply_depots_for_enemies()
        self.micro.manage_squads()
        # logger.info("executing build order")
        await self.build_order.execute()
        # CS: "This will speed up our overall velocity"
        # logger.info("distributing_workers")
        await self.micro.distribute_workers(self.build_order.pending)
        logger.info("ending step")

    async def on_end(self, game_result: Result):
        print("Game ended.")
        logger.info(self.build_order.complete)
        # Do things here after the game ends

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
            logger.info(f"assigned to {self.micro.unassigned_army.name}")

            self.micro.unassigned_army.recruit(unit)


def main():
    run_game(
        maps.get("Equilibrium512AIE"),
        [Bot(Race.Terran, BotTato(), name="BotTato"),
         Computer(Race.Protoss, Difficulty.Medium)],
        realtime=False,
    )


if __name__ == "__main__":
    main()
