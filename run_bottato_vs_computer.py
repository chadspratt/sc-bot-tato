

"""
This script makes sure to run all bots in the examples folder to check if they can launch.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
import random

from loguru import logger

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import AIBuild, Difficulty, Race, Result
from sc2.main import run_game
from sc2.player import Bot, Computer

from bottato.bottato import BotTato

# pyre-ignore[11]
bot_class: type[BotAI] = BotTato

race_dict = {
    None: Race.Random,
    "protoss": Race.Protoss,
    "terran": Race.Terran,
    "zerg": Race.Zerg,
}
build_dict = {
    None: AIBuild.RandomBuild,
    "rush": AIBuild.Rush,
    "timing": AIBuild.Timing,
    "macro": AIBuild.Macro,
    "power": AIBuild.Power,
    "air": AIBuild.Air,
}
map_list = [
    "PersephoneAIE_v4",
    "IncorporealAIE_v4",
    "PylonAIE_v4",
    "TorchesAIE_v4",
    "UltraloveAIE_v2",
    "MagannathaAIE_v2"
]

def init_database():
    """Initialize the SQLite database and create the matches table if it doesn't exist."""
    conn = sqlite3.connect('db/match_data.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS match (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            map_name TEXT NOT NULL,
            opponent_race TEXT NOT NULL,
            opponent_difficulty TEXT NOT NULL,
            opponent_build TEXT NOT NULL,
            result TEXT NOT NULL,
            replay_path TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def save_match_result(map_name: str, opponent_race: Race, opponent_difficulty: Difficulty, opponent_build: AIBuild, result: Result, replay_path: str):
    """Save match result to the database."""
    conn = sqlite3.connect('db/match_data.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO match (timestamp, map_name, opponent_race, opponent_difficulty, opponent_build, result, replay_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        datetime.now().isoformat(),
        map_name,
        opponent_race.name,
        opponent_difficulty.name,
        opponent_build.name,
        result.name,
        replay_path
    ))
    
    conn.commit()
    conn.close()

def main():
    # Initialize database
    init_database()
    
    random_map = random.choice(map_list)
    map = maps.get(random_map)
    race = os.environ.get("RACE")
    build = os.environ.get("BUILD")
    opponent_race = race_dict.get(race, Race.Random)
    opponent_build = build_dict.get(build, AIBuild.RandomBuild)
    # opponent = Computer(opponent_race, Difficulty.CheatInsane, ai_build=opponent_build)
    opponent = Computer(opponent_race, Difficulty.CheatMoney, ai_build=opponent_build)
    replay_name = f"replays/{random_map}_{race}-{build}.SC2Replay"
    
    # disable logging done by LogHelper
    os.environ["LOG_TESTING"] = "1"

    result = run_game(
        map,
        [Bot(Race.Terran, bot_class(), "BotTato"), opponent],
        realtime=False,
        save_replay_as=replay_name,
        game_time_limit=3600,
    )
    
    bottato_result = result[0] if isinstance(result, list) else result
    logger.info(f"\n================================\nResult vs {opponent}: {bottato_result}\n================================")
    
    # Save result to database
    save_match_result(
        random_map,
        opponent_race,
        Difficulty.CheatMoney,
        opponent_build,
        bottato_result,
        replay_name
    )
    
    assert bottato_result == Result.Victory, f"BotTato should win against {opponent}, but got {bottato_result}"


if __name__ == "__main__":
    main()