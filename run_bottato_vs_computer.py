

"""
This script makes sure to run all bots in the examples folder to check if they can launch.
"""

from __future__ import annotations

import asyncio
import os

from loguru import logger

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import AIBuild, Difficulty, Race, Result
from sc2.main import GameMatch, a_run_multiple_games_nokill
from sc2.player import Bot, Computer

from bottato.bottato import BotTato

matches: list[GameMatch] = []

races = [
    Race.Protoss, # type: ignore
    Race.Terran, # type: ignore
    Race.Zerg, # type: ignore
]
builds = [
    AIBuild.Rush, # type: ignore
    AIBuild.Timing, # type: ignore
    AIBuild.Macro, # type: ignore
    AIBuild.Power, # type: ignore
    AIBuild.Air, # type: ignore
]

# pyre-ignore[11]
bot_class: type[BotAI] = BotTato

map = maps.get("PersephoneAIE_v4")
# for race in races:
#     for build in builds:
#         matches.append(
#             GameMatch(
#                 map, # type: ignore
#                 players=[Bot(Race.Terran, bot_class()), Computer(race, Difficulty.VeryHard, ai_build=build)], # type: ignore
#             realtime=False,
#         )
# )

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

async def main():
    race = race_dict.get(os.environ.get("RACE"))
    build = build_dict.get(os.environ.get("BUILD"))
    matches.append(
        GameMatch(
            map, # type: ignore
            players=[Bot(Race.Terran, bot_class(), "BotTato"), Computer(race, Difficulty.VeryHard, ai_build=build)], # type: ignore
        realtime=False,
        )
    )
    os.environ["LOG_TESTING"] = "1"
    results = await a_run_multiple_games_nokill(matches)

    # Verify results
    for result, game_match in zip(results, matches):
        # Zergrush bot sets variable to True when on_end was called
        if hasattr(game_match.players[0], "on_end_called"):
            assert getattr(game_match.players[0], "on_end_called", False) is True
        
        opponent = game_match.players[1]
        bottato_result = result[opponent]
        for player, result in result.items():
            if player.name != "BotTato":
                opponent = player
            else:
                bottato_result = result
        logger.info(f"Result vs {opponent}: {bottato_result}")
        assert bottato_result == Result.Victory, f"BotTato should win against {opponent}, but got {bottato_result}" # type: ignore
    logger.info("Checked all results")


if __name__ == "__main__":
    asyncio.run(main())