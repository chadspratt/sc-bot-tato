import os

from loguru import logger
from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

from bottato.bottato import BotTato


HAS_ROTATED_LOG = False


def rotate_at_start(message, file):
    global HAS_ROTATED_LOG
    try:
        return not HAS_ROTATED_LOG
    finally:
        HAS_ROTATED_LOG = True


logger.add("logs/bot_tato.log", level="INFO", format="{message}", rotation=rotate_at_start)


def main():
    bot = BotTato()
    try:
        run_game(
            maps.get(os.environ.get("SCII_MAP", "Equilibrium512AIE")),
            [
                Bot(Race.Terran, bot, name="BotTato"),
                Computer(Race.Protoss, Difficulty.Medium),
            ],
            realtime=False,
            # save_replay_as=".\\replays\\bottato.sc2replay",
        )
    except ConnectionResetError:
        bot.print_all_timers()


if __name__ == "__main__":
    main()
