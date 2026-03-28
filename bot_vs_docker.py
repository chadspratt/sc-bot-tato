"""Debug BotTato locally (with GUI and breakpoints) against an opponent in Docker.

Both SC2 instances run on the host with visible windows. The Docker container
only runs the opponent's bot logic, connecting back to the host via a WebSocket
relay (Proxy). This gives you:
  - Full visual game for debugging
  - VS Code breakpoints work on the local BotTato
  - Opponent runs in an isolated container (like on the ladder)

Prerequisites:
  - Docker Desktop must be running
  - SC2 must be installed locally (the host runs both SC2 instances)
  - Opponent must exist in test_lab/aiarena/bots/{OPPONENT_NAME}/

Environment variables:
  OPPONENT_NAME    - Name of the opponent bot (folder in aiarena/bots/)
  SCII_MAP         - Map name (default: MagannathaAIE_v2)
  OPPONENT_RACE    - Override race (auto-detected from ladderbots.json if omitted)
"""

import json
import os
import sys
from loguru import logger
from pathlib import Path

from sc2 import maps
from sc2.data import Race
from sc2.main import GameMatch, run_multiple_games
from sc2.player import Bot, DockerBotProcess

from bottato.bottato import BotTato

# Remove the default handler that includes timestamps and other info
logger.remove()
# Add a clean handler that only shows the message
logger.add(sys.stdout, level="INFO", format="{message}")

# --- Configuration ---------------------------------------------------------

BOT_DIR = Path(__file__).resolve().parent
AIARENA_BOTS_DIR = BOT_DIR.parent / "web" / "DjangoLocalApps" / "test_lab" / "aiarena" / "bots"

RACE_MAP = {"terran": Race.Terran, "protoss": Race.Protoss, "zerg": Race.Zerg, "random": Race.Random}
IMAGE = "aiarena/arenaclient-bot:v0.8.0"


def _read_race_from_ladderbots(bot_dir: Path) -> Race | None:
    """Read the bot's race from ladderbots.json (case-insensitive filename)."""
    for name in ("ladderbots.json", "LadderBots.json"):
        path = bot_dir / name
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            bots = data.get("Bots", {})
            if bots:
                race_str = next(iter(bots.values())).get("Race", "").lower()
                return RACE_MAP.get(race_str)
    return None


def main():
    opponent_name = os.environ.get("OPPONENT_NAME")
    if not opponent_name:
        logger.error("Set OPPONENT_NAME env var to a bot folder in aiarena/bots/")
        sys.exit(1)

    opponent_dir = AIARENA_BOTS_DIR / opponent_name
    if not opponent_dir.is_dir():
        logger.error(f"Bot directory not found: {opponent_dir}")
        sys.exit(1)

    # Race: env override > ladderbots.json > default Zerg
    race_override = os.environ.get("OPPONENT_RACE", "").lower()
    opponent_race = RACE_MAP.get(race_override) or _read_race_from_ladderbots(opponent_dir) or Race.Zerg

    bot = BotTato()

    opponent = DockerBotProcess(
        bot_dir=opponent_dir,
        race=opponent_race,
        name=opponent_name,
        image=IMAGE,
        stdout=str(BOT_DIR / "logs" / f"{opponent_name}_docker.log"),
    )

    map_name = os.environ.get("SCII_MAP", "MagannathaAIE_v2")
    logger.info(f"Map: {map_name}")
    logger.info(f"Opponent: {opponent}")

    try:
        results = run_multiple_games([
            GameMatch(
                map_sc2=maps.get(map_name),
                players=[Bot(Race.Terran, bot, name="BotTato"), opponent],
                realtime=False,
            )
        ])
        if results and results[0]:
            for player, result in results[0].items():
                logger.info(f"{player}: {result}")
    except ConnectionResetError:
        bot.print_all_timers()


if __name__ == "__main__":
    main()
