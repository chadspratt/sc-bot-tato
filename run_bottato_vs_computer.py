"""
This script makes sure to run all bots in the examples folder to check if they can launch.
"""

from __future__ import annotations

import os
import pymysql
from datetime import datetime
import random

from loguru import logger

# Database configuration from environment variables
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = int(os.environ.get('DB_PORT', '3306'))
DB_NAME = os.environ.get('DB_NAME', 'sc_bot')
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'default')

def get_db_connection():
    """Create and return a database connection."""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=False
    )

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

def get_next_test_group_id() -> int:
    """Get the next test group ID by incrementing the highest completed test group ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT MAX(test_group_id) FROM `match` WHERE end_timestamp IS NOT NULL
    ''')
    
    result = cursor.fetchone()
    conn.close()
    
    # If no completed matches exist, start at 0, otherwise increment by 1
    return 0 if result is None else result[0] + 1

def create_pending_match(
        test_group_id: int,
        start_timestamp: str,
        map_name: str,
        opponent_race: Race,
        opponent_difficulty: Difficulty,
        opponent_build: AIBuild,
    ) -> int | None:
    """Create a pending match entry and return the match ID."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO `match` (test_group_id, start_timestamp, map_name, opponent_race, opponent_difficulty, opponent_build, result)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
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

def update_match_result(match_id: int, result: str):
    """Update match result in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE `match` 
        SET end_timestamp = NOW(), result = %s
        WHERE id = %s
    ''', (
        result,
        match_id
    ))

    conn.commit()
    conn.close()

def update_match_map(match_id: int, map_name: str):
    """Update the map name for an existing match."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        UPDATE `match` 
        SET map_name = %s
        WHERE id = %s
    ''', (map_name, match_id))

    conn.commit()
    conn.close()

def get_least_used_map(opponent_race: str, opponent_build: str, opponent_difficulty: str) -> str:
    """Update the map name for an existing match."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute('''
        SELECT map_name, count(*) ct
        FROM `match`
        WHERE opponent_race = %s
            AND opponent_build = %s
            AND opponent_difficulty = %s
            AND result IN ("Victory", "Defeat")
            AND test_group_id >= 0
        GROUP BY map_name
        ORDER BY ct
        LIMIT 1
    ''', (opponent_race, opponent_build, opponent_difficulty))

    map_name = cursor.fetchone()
    conn.close()
    return map_name[0] if map_name else random.choice(map_list)


def main():
    race = os.environ.get("RACE")
    build = os.environ.get("BUILD")
    difficulty_env = os.environ.get("DIFFICULTY")
    existing_match_id = os.environ.get("MATCH_ID")
    
    opponent_race = race_dict.get(race, Race.Random)
    opponent_build = build_dict.get(build, AIBuild.RandomBuild)
    difficulty: Difficulty = difficulty_dict.get(difficulty_env, Difficulty.CheatInsane)

    least_used_map = get_least_used_map(opponent_race.name, opponent_build.name, difficulty.name)
    map = maps.get(least_used_map)
    
    opponent = Computer(opponent_race, difficulty, ai_build=opponent_build)
    start_time = datetime.now().isoformat()

    if existing_match_id:
        # Use existing match ID and update it with map name
        match_id = int(existing_match_id)
        update_match_map(match_id, least_used_map)
    else:
        # Fallback: create new match if no ID provided (for backward compatibility)
        test_group_id = get_next_test_group_id()
        match_id = create_pending_match(test_group_id, start_time, least_used_map, opponent_race, difficulty, opponent_build)
        assert match_id is not None, "Failed to create match entry in the database."

    replay_path = f"/root/replays/{match_id}_{least_used_map}_{race}-{build}.SC2Replay"

    # Set match ID as environment variable for the bot
    os.environ["TEST_MATCH_ID"] = str(match_id)

    # disable logging done by LogHelper

    try:
        result: Result | list[Result] = run_game(
            map,
            [Bot(Race.Terran, bot_class(), "BotTato"), opponent],
            realtime=False,
            save_replay_as=replay_path,
            game_time_limit=3600,
        )

        bottato_result = result[0] if isinstance(result, list) else result
        logger.info(f"\n================================\nResult vs {opponent}: {bottato_result}\n================================")

        # Update the existing match entry with the result
        update_match_result(match_id, bottato_result.name)
        
    except Exception as e:
        logger.info(f"\n================================\nResult vs {opponent}: Crash\n================================")
        update_match_result(match_id, "Crash")
        raise e
    
    assert bottato_result == Result.Victory, f"BotTato should win against {opponent}, but got {bottato_result}"


if __name__ == "__main__":
    main()
