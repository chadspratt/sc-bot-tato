from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId


class Micro:
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = 0
        self.bot: BotAI = bot

    def adjust_supply_depots_for_enemies(self):
        # Raise depos when enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.distance_to(depot) < 10:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    break
        # Lower depos when no enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.distance_to(depot) < 15:
                    break
            else:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    async def distribute_workers(self):
        desired_ratio = 2
        cooldown = 3
        if (
            self.bot.time - self.last_worker_stop > cooldown
            and self.bot.vespene
            and self.bot.minerals
        ):
            if self.bot.minerals / self.bot.vespene > desired_ratio:
                # mineral glut
                # unassign a bot
                # have vespine capacity available?
                for building in self.bot.gas_buildings.ready:
                    if building.surplus_harvesters < 0:
                        self.bot.workers.gathering.random.stop()
                        self.last_worker_stop = self.bot.time
                        break
            if self.bot.vespene / self.bot.minerals > desired_ratio:
                self.bot.workers.gathering.random.stop()
                self.last_worker_stop = self.bot.time
        await self.bot.distribute_workers()
        logger.info(
            [
                worker.orders[0].ability.id
                for worker in self.bot.workers
                if worker.orders
            ]
        )
