"""
Run BotTato by continuing from a replay at a specified game loop.

Environment variables:
  REPLAY_PATH              - Path to .SC2Replay file inside the container
  TAKEOVER_GAME_LOOP       - Game loop at which the bot takes over
  BOT_PLAYER_ID            - Which player in the replay BotTato replaces (1 or 2, default: 1)
  DIFFICULTY               - Computer opponent difficulty (default: CheatInsane)
  MATCH_ID                 - (optional) existing match row to update in DB
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from loguru import logger

import pymysql
from sc2.data import AIBuild, Difficulty, Race, Result
from sc2.player import Bot, Computer
from sc2.replay_continuation import run_game_from_replay

from bottato.bottato import BotTato

# Database configuration from environment variables
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = int(os.environ.get('DB_PORT', '3306'))
DB_NAME = os.environ.get('DB_NAME', 'sc_bot')
DB_USER = os.environ.get('DB_USER', 'root')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'default')

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


def get_db_connection():
    """Create and return a database connection."""
    return pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        autocommit=False,
    )


def update_match_result(match_id: int, result: str):
    """Update match result in the database."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE `match` SET end_timestamp = NOW(), result = %s WHERE id = %s',
        (result, match_id),
    )
    conn.commit()
    conn.close()


def update_match_map(match_id: int, map_name: str):
    """Update the map name for an existing match."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE `match` SET map_name = %s WHERE id = %s',
        (map_name, match_id),
    )
    conn.commit()
    conn.close()


def main():
    replay_path = os.environ.get("REPLAY_PATH")
    takeover_loop_str = os.environ.get("TAKEOVER_GAME_LOOP")
    bot_player_id = int(os.environ.get("BOT_PLAYER_ID", "1"))
    difficulty_env = os.environ.get("DIFFICULTY")
    existing_match_id = os.environ.get("MATCH_ID")

    if not replay_path:
        logger.error("REPLAY_PATH environment variable is required")
        sys.exit(1)

    if not takeover_loop_str:
        logger.error("TAKEOVER_GAME_LOOP environment variable is required")
        sys.exit(1)

    takeover_game_loop = int(takeover_loop_str)
    difficulty: Difficulty = difficulty_dict.get(difficulty_env, Difficulty.CheatInsane)

    match_id: int | None = int(existing_match_id) if existing_match_id else None

    logger.info(f"Continue from replay: {replay_path}")
    logger.info(f"Takeover at game loop: {takeover_game_loop} (~{takeover_game_loop / 22.4:.0f}s)")
    logger.info(f"Bot player ID: {bot_player_id}, Difficulty: {difficulty}")

    # Set match ID as environment variable for the bot
    if match_id:
        os.environ["TEST_MATCH_ID"] = str(match_id)

    # Set takeover time so BotTato can offset self.time
    takeover_time_seconds = takeover_game_loop / 22.4
    os.environ["REPLAY_TAKEOVER_TIME"] = str(takeover_time_seconds)
    logger.info(f"Set REPLAY_TAKEOVER_TIME={takeover_time_seconds:.1f}s")

    output_replay_path = None
    if match_id:
        output_replay_path = f"/root/replays/{match_id}_continued.SC2Replay"

    try:
        # The opponent race will be determined from the replay automatically
        # by run_game_from_replay (it overrides Computer race to match replay)
        result: Result = run_game_from_replay(
            replay_path=replay_path,
            target_game_loop=takeover_game_loop,
            players=[
                Bot(Race.Terran, BotTato(), "BotTato"),
                Computer(Race.Random, difficulty),  # Race will be overridden from replay
            ],
            bot_player_id=bot_player_id,
            realtime=False,
            save_replay_as=output_replay_path,
            game_time_limit=3600,
        )

        logger.info(
            f"\n================================\n"
            f"Result (continued from replay): {result}\n"
            f"================================"
        )

        if match_id:
            update_match_result(match_id, result.name)

    except Exception as e:
        logger.error(
            f"\n================================\n"
            f"Crash during continue-from-replay: {e}\n"
            f"================================"
        )
        if match_id:
            update_match_result(match_id, "Crash")
        raise e


if __name__ == "__main__":
    main()
