from __future__ import annotations

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.ability_id import AbilityId
from .base_unit_micro import BaseUnitMicro
from ..enemy import Enemy
from ..mixins import GeometryMixin


class BansheeMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.51

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if self.bot.can_cast(unit, AbilityId.BEHAVIOR_CLOAKON_BANSHEE) and self.enemy.threats_to(unit):
            unit(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
