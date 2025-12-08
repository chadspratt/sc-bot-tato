

"""
This script makes sure to run all bots in the examples folder to check if they can launch.
"""

from __future__ import annotations

import asyncio
import os
from random import random

from loguru import logger

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import AIBuild, Difficulty, Race, Result
from sc2.main import GameMatch, maintain_SCII_count, run_match
from sc2.player import Bot, Computer

from bottato.bottato import BotTato

# pyre-ignore[11]
bot_class: type[BotAI] = BotTato

race_dict = {
    None: Race.Random, # type: ignore
    "protoss": Race.Protoss, # type: ignore
    "terran": Race.Terran, # type: ignore
    "zerg": Race.Zerg, # type: ignore
}
build_dict = {
    None: AIBuild.RandomBuild, # type: ignore
    "rush": AIBuild.Rush, # type: ignore
    "timing": AIBuild.Timing, # type: ignore
    "macro": AIBuild.Macro, # type: ignore
    "power": AIBuild.Power, # type: ignore
    "air": AIBuild.Air, # type: ignore
}
map_list = [
    "PersephoneAIE_v4",
    "IncorporealAIE_v4",
    "PylonAIE_v4",
    "TorchesAIE_v4",
    "UltraloveAIE_v2",
    "MagannathaAIE_v2"
]

async def main():
    race = race_dict.get(os.environ.get("RACE"))
    build = build_dict.get(os.environ.get("BUILD"))
    random_map = map_list[int(random() * len(map_list))]
    map = maps.get(random_map)
    
    game_match = GameMatch(
        map, # type: ignore
        players=[Bot(Race.Terran, bot_class(), "BotTato"), Computer(race, Difficulty.VeryHard, ai_build=build)], # type: ignore
        realtime=False,
    )
    
    # disable logging done by LogHelper
    os.environ["LOG_TESTING"] = "1"

    controllers = []
    await maintain_SCII_count(game_match.needed_sc2_count, controllers, game_match.sc2_config)
    result = await run_match(controllers, game_match, False)

    # Verify results
    if hasattr(game_match.players[0], "on_end_called"):
        assert getattr(game_match.players[0], "on_end_called", False) is True
    
    opponent = [player for player in result.keys() if player.name != "BotTato"][0]
    bottato_result = [result for player, result in result.items() if player.name == "BotTato"][0]
    logger.info(f"================================\nResult vs {opponent}: {bottato_result}\n================================")
    assert bottato_result == Result.Victory, f"BotTato should win against {opponent}, but got {bottato_result}" # type: ignore


if __name__ == "__main__":
    asyncio.run(main())