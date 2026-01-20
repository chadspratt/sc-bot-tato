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

difficulty_dict = {
    None: Difficulty.CheatInsane,
    "Easy": Difficulty.Easy,
    "Medium": Difficulty.Medium,
    "MediumHard": Difficulty.MediumHard,
    "Hard": Difficulty.Hard,
    "Harder": Difficulty.Harder,
    "VeryHard": Difficulty.VeryHard,
    "CheatVision": Difficulty.CheatVision,
    "CheatMoney": Difficulty.CheatMoney,
    "CheatInsane": Difficulty.CheatInsane,
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
            test_group_id INTEGER,
            start_timestamp TEXT NOT NULL,
            end_timestamp TEXT,
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

def get_next_test_group_id() -> int:
    """Get the next test group ID by incrementing the highest completed test group ID."""
    conn = sqlite3.connect('db/match_data.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT MAX(test_group_id) FROM match WHERE end_timestamp IS NOT NULL
    ''')
    
    result = cursor.fetchone()[0]
    conn.close()
    
    # If no completed matches exist, start at 0, otherwise increment by 1
    return 0 if result is None else result + 1

def create_pending_match(
        test_group_id: int,
        start_timestamp: str,
        map_name: str,
        opponent_race: Race,
        opponent_difficulty: Difficulty,
        opponent_build: AIBuild,
    ) -> int | None:
    """Create a pending match entry and return the match ID."""
    conn = sqlite3.connect('db/match_data.db')
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO match (test_group_id, start_timestamp, map_name, opponent_race, opponent_difficulty, opponent_build, result)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        test_group_id,
        start_timestamp,
        map_name,
        opponent_race.name,
        opponent_difficulty.name,
        opponent_build.name,
        "Pending"
    ))

    match_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return match_id

def update_match_result(match_id: int, result: str, replay_path: str):
    """Update match result in the database."""
    conn = sqlite3.connect('db/match_data.db')
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE match 
        SET end_timestamp = ?, result = ?, replay_path = ?
        WHERE id = ?
    ''', (
        datetime.now().isoformat(),
        result,
        replay_path,
        match_id
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
    difficulty_env = os.environ.get("DIFFICULTY")
    
    opponent_race = race_dict.get(race, Race.Random)
    opponent_build = build_dict.get(build, AIBuild.RandomBuild)
    difficulty: Difficulty = difficulty_dict.get(difficulty_env, Difficulty.CheatInsane)
    
    opponent = Computer(opponent_race, difficulty, ai_build=opponent_build)
    start_time = datetime.now().isoformat()

    # Get the next test group ID
    test_group_id = get_next_test_group_id()

    # Create pending match entry and get match ID
    match_id = create_pending_match(test_group_id, start_time, random_map, opponent_race, difficulty, opponent_build)
    assert match_id is not None, "Failed to create match entry in the database."

    replay_name = f"replays/{match_id}_{random_map}_{race}-{build}.SC2Replay"

    # Set match ID as environment variable for the bot
    os.environ["TEST_MATCH_ID"] = str(match_id)

    # disable logging done by LogHelper
    # os.environ["SC_BOT_AUTOMATED_TEST"] = "1"

    try:
        result: Result | list[Result] = run_game(
            map,
            [Bot(Race.Terran, bot_class(), "BotTato"), opponent],
            realtime=False,
            save_replay_as=replay_name,
            game_time_limit=3600,
        )

        bottato_result = result[0] if isinstance(result, list) else result
        logger.info(f"\n================================\nResult vs {opponent}: {bottato_result}\n================================")

        # Update the existing match entry with the result
        update_match_result(match_id, bottato_result.name, replay_name)
        
    except Exception as e:
        logger.info(f"\n================================\nResult vs {opponent}: Crash\n================================")
        update_match_result(match_id, "Crash", replay_name)
        raise e
    
    assert bottato_result == Result.Victory, f"BotTato should win against {opponent}, but got {bottato_result}"


if __name__ == "__main__":
    main()
