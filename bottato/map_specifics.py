from typing import List, Tuple

from sc2.bot_ai import BotAI
from sc2.position import Point2


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
        
    @staticmethod
    def no_fly_zones(bot: BotAI) -> List[Tuple[Point2, float]]:
        if bot.game_info.map_name == "Persephone AIE":
            return [(Point2((102.5, 90)), 3.5)]
        return []