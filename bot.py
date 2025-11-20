import os
from typing import TextIO

from loguru import logger
from sc2 import maps
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.data import AIBuild

from bottato.bottato import BotTato
# from other_bots.QueenBot.bot import main as QueenBot


has_rotate_log: bool = False


def rotate_at_start(message, file: TextIO) -> bool:
    global has_rotate_log
    try:
        return not has_rotate_log
    finally:
        has_rotate_log = True


logger.add("logs/bot_tato.log", level="INFO", format="{message}", rotation=rotate_at_start)


def main():
    bot = BotTato()
    # bot2 = QueenBot()
    try:
        run_game(
            maps.get(os.environ.get("SCII_MAP", "PersephoneAIE_v4")),
            # IncorporealAIE_v4, PylonAIE_v4, TorchesAIE_v4, UltraloveAIE_v2, MagannathaAIE_v2, PersephoneAIE_v4
            [
                Bot(Race.Terran, bot, name="BotTato"), # type: ignore
                # Bot(Race.Zerg, bot2, name="QueenBot"),
                # Protoss, Terran, Zerg, Random
                # VeryEasy, Easy, Medium, MediumHard, Hard, Harder, VeryHard, CheatVision, CheatMoney, CheatInsane
                # RandomBuild, Rush, Timing, Power, Macro, Air
                Computer(Race.Terran, Difficulty.CheatMoney, ai_build=AIBuild.Power), # type: ignore
            ],
            realtime=False,
            random_seed=30,
            # 30 and 33 give different spawns for all maps
            # 39 - lings arrive before reactor
        )
    except ConnectionResetError:
        bot.print_all_timers()


if __name__ == "__main__":
    main()
