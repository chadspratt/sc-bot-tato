from __future__ import annotations

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base_unit_micro import BaseUnitMicro
from ..enemy import Enemy
from ..mixins import GeometryMixin


class BansheeMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.51

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float) -> bool:
        return False
