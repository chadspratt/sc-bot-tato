from __future__ import annotations

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.units import Units


def get_refresh_references(units: Units, bot: BotAI) -> Units:
    _units = []
    for unit in units:
        try:
            _units.append(bot.all_units.by_tag(unit.tag))
        except KeyError:
            logger.info(f"Couldn't find unit {unit}!")
    return Units(_units, bot_object=bot)
