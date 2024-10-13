import os

from loguru import logger
from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

from bottato.bottato import BotTato


logger.add("logs/bot_tato.log", level="INFO", format="{message}", rotation=True)


def main():
    bot = BotTato()
    try:
        run_game(
            maps.get(os.environ.get("SCII_MAP", "Equilibrium513AIE")),
            [
                Bot(Race.Terran, bot, name="BotTato"),
                Computer(Race.Terran, Difficulty.VeryHard),
            ],
            realtime=False,
            # save_replay_as=".\\replays\\bottato.sc2replay",
        )
    except ConnectionResetError:
        bot.print_all_timers()


if __name__ == "__main__":
    main()
