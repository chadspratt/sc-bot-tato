from sc2.bot_ai import BotAI
from sc2.data import Result
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId

from bottato.build_step import BuildOrder
from bottato.micro import Micro


class BotTato(BotAI):

    async def on_start(self):
        self.build_order: BuildOrder = BuildOrder('tvt1')

    async def on_step(self, iteration):
        ccs: Units = self.townhalls(UnitTypeId.COMMANDCENTER)
        if not ccs:
            return

        # cc: Unit = ccs.first

        await self.distribute_workers()

        Micro.adjust_supply_depots_for_enemies(self)

        self.build_order.execute(self)

    async def on_end(self, game_result: Result):
        print("Game ended.")
        # Do things here after the game ends
