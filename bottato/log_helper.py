import os
import sqlite3
from loguru import logger
from typing import List

from sc2.bot_ai import BotAI

# Try to import pymysql - it will be available in local testing, not on server
try:
    import pymysql
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False


class LogHelper:
    previous_messages: dict[str, int] = {}
    new_messages: List[str] = []
    chat_messages: List[str] = []
    db_messages: List[str] = []

    bot: BotAI

    testing: bool = False
    test_match_id: int | None = None
    use_mariadb: bool = False

    @staticmethod
    def init(bot: BotAI):
        LogHelper.bot = bot
        match_id = os.environ.get("TEST_MATCH_ID")
        if match_id is not None:
            LogHelper.test_match_id = int(match_id)
        # Use MariaDB only if pymysql is available AND we're in local testing mode
        LogHelper.use_mariadb = PYMYSQL_AVAILABLE and LogHelper.test_match_id is not None
        LogHelper.add_log(f"LogHelper initialized. Test Match ID: {LogHelper.test_match_id}, Using MariaDB: {LogHelper.use_mariadb}")
        # enable writing to an sqlite db on the ladder
        # if not LogHelper.use_mariadb:
        #     LogHelper.test_match_id = 0

    @staticmethod
    def add_log(message: str):
        if LogHelper.testing:
            return
        LogHelper.new_messages.append(message)

    @staticmethod
    async def add_chat(message: str):
        if LogHelper.testing:
            return
        if message not in LogHelper.chat_messages:
            await LogHelper.bot.client.chat_send(message, False)
            LogHelper.chat_messages.append(message)
            LogHelper.new_messages.append(message)

    @staticmethod
    def print_logs(iteration: int):
        if LogHelper.testing:
            return
        formatted_time = LogHelper.bot.time_formatted
        for message in LogHelper.new_messages:
            if message not in LogHelper.previous_messages:
                logger.info(f"{iteration} - {formatted_time}: {message}")
                LogHelper.previous_messages[message] = 1
            else:
                LogHelper.previous_messages[message] += 1
        to_delete = []
        for message in LogHelper.previous_messages:
            if message not in LogHelper.new_messages:
                to_delete.append(message)
                if LogHelper.previous_messages[message] > 1:
                    logger.info(f"{iteration} - {formatted_time}: ended ({LogHelper.previous_messages[message]}x): {message}")
        for message in to_delete:
            del LogHelper.previous_messages[message]
        LogHelper.new_messages = []

    @staticmethod
    def update_match_duration(duration_seconds: int):
        """Update the match duration in the database if we're in testing mode."""
        LogHelper.write_log_to_db("Match ended", str(LogHelper.bot.time))

    @staticmethod
    def write_log_to_db(type: str, message: str, override_time: float | None = None):
        """Update the match duration in the database if we're in testing mode."""
        LogHelper.add_log(message)
        if LogHelper.test_match_id is None:
            return
        # if message not in LogHelper.db_messages:
        LogHelper.db_messages.append(message)
        
        timestamp = override_time if override_time else LogHelper.bot.time
        
        if LogHelper.use_mariadb:
            # Use MariaDB for local testing
            conn = pymysql.connect( # type: ignore always defined if USE_MARIADB is True
                host=os.environ.get('DB_HOST', 'localhost'),
                port=int(os.environ.get('DB_PORT', '3306')),
                user=os.environ.get('DB_USER', 'root'),
                password=os.environ.get('DB_PASSWORD', 'default'),
                database=os.environ.get('DB_NAME', 'sc_bot'),
                autocommit=False
            )
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO match_event (match_id, type, message, game_timestamp)
                VALUES (%s, %s, %s, %s)
            ''', (int(LogHelper.test_match_id), type, message, timestamp))
            if type == "Match ended":
                cursor.execute('''
                    UPDATE `match` SET duration_in_game_time = %s
                    WHERE id = %s
                ''', (int(timestamp), LogHelper.test_match_id))
                conn.commit()
        else:
            # Use SQLite for server matches
            conn = sqlite3.connect('../db/match_data.db')
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO match_event (match_id, type, message, game_timestamp)
                VALUES (?, ?, ?, ?)
            ''', (LogHelper.test_match_id, type, message, timestamp))
        
        conn.commit()
        conn.close()
