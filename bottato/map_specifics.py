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
    
    @staticmethod
    def bad_for_proxy(bot: BotAI) -> bool:
        return bot.game_info.map_name in ["Ultralove AIE"]
    
    @staticmethod
    def worker_scout_midway_point(bot: BotAI) -> Point2 | None:
        # maps with rotational symmetry can have different default paths between bases
        # take the non-default to increase chance of scouting worker rush early
        if bot.game_info.map_name == "Ultralove AIE":
            if bot.start_location == Point2((42.5, 46.5)):
                return Point2((87.5, 96.5))
            return Point2((96.5, 87.5))
        elif bot.game_info.map_name == "Incorporeal AIE":
            if bot.start_location == Point2((123.5, 24.5)):
                return Point2((90, 97))
            return Point2((66, 69))
        elif bot.game_info.map_name == "Pylon AIE":
            if bot.start_location == Point2((175.5, 76.5)):
                return Point2((132, 126))
            return Point2((115, 122))
        return None