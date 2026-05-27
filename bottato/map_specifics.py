from sc2.bot_ai import BotAI


class MapSpecifics:
    @staticmethod
    def has_ground_healing_shrines(bot: BotAI) -> bool:
        return bot.game_info.map_name in ["Persephone AIE", "Torches AIE"]
    @staticmethod
    def has_air_healing_shrines(bot: BotAI) -> bool:
        return bot.game_info.map_name in ["Torches AIE"]
    @staticmethod
    def base_location_might_be_blocked(bot: BotAI) -> bool:
        return bot.game_info.map_name in ["Magannatha AIE"]