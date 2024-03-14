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
logger.add("bot_tato.log", level="INFO")


class BotTato(BotAI):

    async def on_start(self):
        self.build_order: BuildOrder = BuildOrder('tvt1')
        self.micro = Micro()

    async def on_step(self, iteration):
        ccs: list[Unit] = self.townhalls(UnitTypeId.COMMANDCENTER)
        if not ccs:
            return
        await self.distribute_workers()
        self.micro.adjust_supply_depots_for_enemies(self)
        await self.build_order.execute(self)

    async def on_end(self, game_result: Result):
        print("Game ended.")
        # Do things here after the game ends

    async def on_building_construction_started(self, unit: Unit):
        logger.info(f"building started! {unit}")
        self.build_order.recently_started_units.append(unit)

    async def on_building_construction_complete(self, unit: Unit):
        logger.info(f"building complete! {unit}")
        self.build_order.recently_completed_units.append(unit)

    async def on_unit_created(self, unit: Unit):
        logger.info(f"raising complete! {unit}")
        self.build_order.recently_completed_units.append(unit)

    
def main():
    run_game(
        maps.get("Equilibrium512AIE"),
        [Bot(Race.Terran, BotTato(), name="BotTato"),
         Computer(Race.Protoss, Difficulty.Medium)],
        realtime=False,
    )


if __name__ == "__main__":
    main()
