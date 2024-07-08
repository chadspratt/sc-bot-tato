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

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def retreat(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        if await self.grenade_knock_away(unit, enemy.threats_to(unit)):
            return True
        return await super().retreat(unit, enemy, health_threshold)

    async def grenade_knock_away(self, unit: Unit, targets: Units) -> bool:
        grenade_targets = []
        if targets and await self.grenade_available(unit):
            for target in targets:
                future_target_position = self.predict_future_unit_position(target, self.grenade_timer)
                grenade_target = future_target_position.towards(unit)
                if unit.in_ability_cast_range(AbilityId.KD8CHARGE_KD8CHARGE, grenade_target):
                    logger.info(f"{unit} grenade candidates {target}: {future_target_position} -> {grenade_target}")
                    grenade_targets.append(grenade_target)

        if grenade_targets:
            # choose furthest to reduce chance of grenading self
            grenade_target = unit.position.furthest(grenade_targets)
            logger.info(f"{unit} grenading {grenade_target}")
            self.throw_grenade(unit, grenade_target)
            return True

        return False

    async def grenade_jump(self, unit: Unit, target: Unit) -> bool:
        if await self.grenade_available(unit):
            logger.info(f"{unit} grenading {target}")
            self.throw_grenade(unit, self.predict_future_unit_position(target, self.grenade_timer))
            return True
        return False

    def throw_grenade(self, unit: Unit, target: Point2):
        unit(AbilityId.KD8CHARGE_KD8CHARGE, target)

    async def grenade_available(self, unit: Unit) -> bool:
        try:
            return await self.bot.can_cast(unit, AbilityId.KD8CHARGE_KD8CHARGE, only_check_energy_and_cooldown=True)
        except ProtocolError:
            return False
