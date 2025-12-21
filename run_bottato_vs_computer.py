

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
from sc2.main import GameMatch, maintain_SCII_count, run_match, run_game
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

def main():
    random_map = map_list[int(random() * len(map_list))]
    map = maps.get(random_map)
    race = os.environ.get("RACE")
    build = os.environ.get("BUILD")
    opponent_race = race_dict.get(race)
    opponent_build = build_dict.get(build)
    opponent = Computer(opponent_race, Difficulty.CheatMoney, ai_build=opponent_build) # type: ignore
    replay_name = f"replays/{random_map}_{race}-{build}.SC2Replay"
    
    # disable logging done by LogHelper
    os.environ["LOG_TESTING"] = "1"

    result = run_game(
        map,
        [Bot(Race.Terran, bot_class(), "BotTato"), opponent], # type: ignore
        realtime=False,
        save_replay_as=replay_name,
        game_time_limit=3600,
    )
    
    bottato_result = result[0] if isinstance(result, list) else result
    logger.info(f"================================\nResult vs {opponent}: {bottato_result}\n================================")
    assert bottato_result == Result.Victory, f"BotTato should win against {opponent}, but got {bottato_result}" # type: ignore


if __name__ == "__main__":
    main()