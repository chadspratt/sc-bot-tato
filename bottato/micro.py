from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId


class Micro:
    def adjust_supply_depots_for_enemies(self, bot: BotAI):
        # Raise depos when enemies are nearby
        for depot in bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for enemy_unit in bot.enemy_units:
                if enemy_unit.distance_to(depot) < 10:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    break
        # Lower depos when no enemies are nearby
        for depot in bot.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for enemy_unit in bot.enemy_units:
                if enemy_unit.distance_to(depot) < 15:
                    break
            else:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)
