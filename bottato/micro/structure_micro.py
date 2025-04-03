from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from .base_unit_micro import BaseUnitMicro


class StructureMicro(BaseUnitMicro):
    def __init__(self, bot: BotAI) -> None:
        self.bot: BotAI = bot
        self.formations = []

    async def execute(self):
        # logger.info("adjust_supply_depots_for_enemies step")
        self.adjust_supply_depots_for_enemies()
        self.target_autoturrets()

    def adjust_supply_depots_for_enemies(self):
        # Raise depos when enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for enemy_unit in self.bot.enemy_units:
                try:
                    if enemy_unit.distance_to(depot) < 3:
                        depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                        break
                except IndexError:
                    continue
        # Lower depos when no enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.distance_to(depot) < 8:
                    break
            else:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    def target_autoturrets(self):
        turret: Unit
        for turret in self.bot.structures(UnitTypeId.AUTOTURRET):
            logger.debug(f"turret {turret} attacking")
            self.attack_something(turret, 0)
