import os
import sqlite3
from loguru import logger
from typing import List

from sc2.bot_ai import BotAI


class LogHelper:
    previous_messages: dict[str, int] = {}
    new_messages: List[str] = []
    chat_messages: List[str] = []

    bot: BotAI

    testing: bool = False
    test_match_id: str | None = None
    @staticmethod
    def init(bot: BotAI):
        LogHelper.bot = bot
        LogHelper.testing = os.environ.get("SC_BOT_AUTOMATED_TEST") == "1"
        LogHelper.test_match_id = os.environ.get("TEST_MATCH_ID")
        LogHelper.add_log(f"LogHelper initialized. Testing mode: {LogHelper.testing}, Test Match ID: {LogHelper.test_match_id}")

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
    def print_logs():
        if LogHelper.testing:
            return
        formatted_time = LogHelper.bot.time_formatted
        for message in LogHelper.new_messages:
            if message not in LogHelper.previous_messages:
                logger.info(f"{formatted_time}: {message}")
                LogHelper.previous_messages[message] = 1
            else:
                LogHelper.previous_messages[message] += 1
        to_delete = []
        for message in LogHelper.previous_messages:
            if message not in LogHelper.new_messages:
                to_delete.append(message)
                if LogHelper.previous_messages[message] > 1:
                    logger.info(f"{formatted_time}: ended ({LogHelper.previous_messages[message]}x): {message}")
        for message in to_delete:
            del LogHelper.previous_messages[message]
        LogHelper.new_messages = []

    @staticmethod
    def update_match_duration(duration_seconds: int):
        """Update the match duration in the database if we're in testing mode."""
        if LogHelper.test_match_id is None:
            return
            
        conn = sqlite3.connect('db/match_data.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE match 
            SET duration_in_game_time = ?
            WHERE id = ?
        ''', (duration_seconds, int(LogHelper.test_match_id)))
        
        conn.commit()
        conn.close()
