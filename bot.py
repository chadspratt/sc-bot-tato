import os
import sys
from loguru import logger

from sc2 import maps
from sc2.data import AIBuild, Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer

from bottato.bottato import BotTato

# from other_bots.QueenBot.bot import main as QueenBot

# Remove the default handler that includes timestamps and other info
logger.remove()
# Add a clean handler that only shows the message
logger.add(sys.stdout, level="INFO", format="{message}")

def main():
    bot = BotTato()
    # bot2 = QueenBot()
    try:
        run_game(
            # This file is only used for debugging. these values are meant to be changed as-needed so don't commit changes to them.
            # IncorporealAIE_v4, PylonAIE_v4, TorchesAIE_v4, UltraloveAIE_v2, MagannathaAIE_v2, PersephoneAIE_v4
            maps.get(os.environ.get("SCII_MAP", "MagannathaAIE_v2")),
            [
                Bot(Race.Terran, bot, name="BotTato"),
                # Bot(Race.nearest_priority, bot2, name="QueenBot"),
                # Protoss, Terran, Zerg, Random
                # VeryEasy, Easy, Medium, MediumHard, Hard, Harder, VeryHard, CheatVision, CheatMoney, CheatInsane
                # RandomBuild, Rush, Timing, Power, Macro, Air
                Computer(Race.Protoss, Difficulty.CheatInsane, ai_build=AIBuild.Air),
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
