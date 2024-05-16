from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class ReaperMicro(BaseUnitMicro, GeometryMixin):
    grenade_cooldown = 14.0
    grenade_timer = 1.7

    def __init__(self, unit: Unit, bot: BotAI):
        super().__init__(unit, bot)

    async def retreat(self, enemy: Enemy, health_threshold: float) -> bool:
        can_grenade_1: bool = await self.grenade_available
        logger.info(f"{self.unit} grenade available: {can_grenade_1}")
        # if await self.grenade_jump(enemy.threats_to(self.unit)):
        #     return True
        return await super().retreat(enemy, health_threshold)

    async def grenade_jump(self, target: Unit) -> bool:
        if await self.grenade_available:
            logger.info(f"{self.unit} grenading {target}")
            self.unit(AbilityId.KD8CHARGE_KD8CHARGE, self.predict_future_unit_position(target, self.grenade_timer))
            return True
        return False

    @property
    async def grenade_available(self) -> bool:
        return await self.bot.can_cast(self.unit, AbilityId.KD8CHARGE_KD8CHARGE, only_check_energy_and_cooldown=True)
