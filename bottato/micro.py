from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

from .workers import Workers
from .military import Military
from bottato.build_step import BuildStep


class Micro:
    def __init__(self, bot: BotAI) -> None:
        self.workers = Workers(bot)
        self.military = Military(bot)
        self.last_worker_stop = 0
        self.bot: BotAI = bot
        self.formations = []
        self.enemies_in_view = []

    async def execute(self, pending_build_steps: list[BuildStep]):
        self.calculate_first_resource_shortage(pending_build_steps)
        # logger.info("distributing_workers")
        await self.workers.distribute_workers()
        # logger.info("adjust_supply_depots_for_enemies step")
        self.adjust_supply_depots_for_enemies()
        self.manage_squads()

    def manage_squads(self):
        self.military.manage_squads(self.enemies_in_view)
        self.enemies_in_view = []

    def calculate_first_resource_shortage(self, pending_build_steps: list[BuildStep]):
        if not pending_build_steps:
            self.workers.minerals_needed = 0
            self.workers.vespene_needed = 0
            return

        self.workers.minerals_needed = -self.bot.minerals
        self.workers.vespene_needed = -self.bot.vespene

        # find first shortage
        for idx, build_step in enumerate(pending_build_steps):
            self.workers.minerals_needed += build_step.cost.minerals
            self.workers.vespene_needed += build_step.cost.vespene
            if self.workers.minerals_needed > 0 or self.workers.vespene_needed > 0:
                break
        logger.info(
            f"next {idx + 1} builds "
            f"vespene: {self.bot.vespene}/{self.workers.vespene_needed + self.bot.vespene}, "
            f"minerals: {self.bot.minerals}/{self.workers.minerals_needed + self.bot.minerals}"
        )

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
