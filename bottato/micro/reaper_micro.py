from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.protocol import ProtocolError
from .base_unit_micro import BaseUnitMicro
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
        logger.debug(f"{self.unit} grenade available: {can_grenade_1}")
        if await self.grenade_knock_away(enemy.threats_to(self.unit)):
            return True
        return await super().retreat(enemy, health_threshold)

    async def grenade_knock_away(self, targets: Units) -> bool:
        grenade_targets = []
        if targets and await self.grenade_available:
            for target in targets:
                future_target_position = self.predict_future_unit_position(target, self.grenade_timer)
                grenade_target = future_target_position.towards(self.unit)
                if self.unit.in_ability_cast_range(AbilityId.KD8CHARGE_KD8CHARGE, grenade_target):
                    logger.info(f"{self.unit} grenade candidates {target}: {future_target_position} -> {grenade_target}")
                    grenade_targets.append(grenade_target)

        if grenade_targets:
            # choose furthest to reduce chance of grenading self
            grenade_target = self.unit.position.furthest(grenade_targets)
            logger.info(f"{self.unit} grenading {grenade_target}")
            self.throw_grenade(grenade_target)
            return True

        return False

    async def grenade_jump(self, target: Unit) -> bool:
        if await self.grenade_available:
            logger.info(f"{self.unit} grenading {target}")
            self.throw_grenade(self.predict_future_unit_position(target, self.grenade_timer))
            return True
        return False

    def throw_grenade(self, target: Point2):
        self.unit(AbilityId.KD8CHARGE_KD8CHARGE, target)

    @property
    async def grenade_available(self) -> bool:
        try:
            return await self.bot.can_cast(self.unit, AbilityId.KD8CHARGE_KD8CHARGE, only_check_energy_and_cooldown=True)
        except ProtocolError:
            return False
