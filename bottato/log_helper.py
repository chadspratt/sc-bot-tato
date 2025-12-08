from loguru import logger
from typing import List

from sc2.bot_ai import BotAI


class LogHelper:
    previous_messages: dict[str, int] = {}
    new_messages: List[str] = []

    bot: BotAI

    testing: bool = False

    @staticmethod
    def add_log(message: str):
        if LogHelper.testing:
            return
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
            if message not in LogHelper.new_messages and LogHelper.previous_messages[message] > 1:
                logger.info(f"{formatted_time}: ended ({LogHelper.previous_messages[message]}x): {message}")
                to_delete.append(message)
        for message in to_delete:
            del LogHelper.previous_messages[message]
        LogHelper.new_messages = []
