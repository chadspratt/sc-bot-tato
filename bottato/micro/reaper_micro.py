from __future__ import annotations

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base import BaseUnitMicro


class ReaperMicro(BaseUnitMicro):
    def __init__(self, unit: Unit, bot: BotAI):
        super().__init__(unit, bot)
