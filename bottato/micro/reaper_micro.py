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

    grenade_cooldowns: dict[int, int] = {}
    unconfirmed_grenade_throwers: list[int] = []

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        return await self.grenade_knock_away(unit, enemy)

    def attack_something(self, unit, enemy: Enemy, health_threshold, targets: Unit = None, force_move: bool = False):
        targets = self.enemy.get_enemies_in_range(unit, include_structures=False, include_units=True, include_destructables=False)
        return super().attack_something(unit, enemy, health_threshold, targets)

    async def grenade_knock_away(self, unit: Unit, enemy: Enemy) -> bool:
        targets: Units = enemy.threats_to(unit)
        grenade_targets = []
        if targets and await self.grenade_available(unit):
            for target in targets:
                if target.is_flying:
                    continue
                future_target_position = enemy.get_predicted_position(target, self.grenade_timer)
                future_target_position = target.position
                grenade_target = future_target_position.towards(unit)
                if unit.in_ability_cast_range(AbilityId.KD8CHARGE_KD8CHARGE, grenade_target):
                    logger.debug(f"{unit} grenade candidates {target}: {future_target_position} -> {grenade_target}")
                    grenade_targets.append(grenade_target)

        if grenade_targets:
            # choose furthest to reduce chance of grenading self
            grenade_target = unit.position.furthest(grenade_targets)
            logger.debug(f"{unit} grenading {grenade_target}")
            self.throw_grenade(unit, grenade_target)
            return True

        return False

    async def grenade_jump(self, unit: Unit, target: Unit) -> bool:
        if await self.grenade_available(unit):
            logger.debug(f"{unit} grenading {target}")
            self.throw_grenade(unit, self.predict_future_unit_position(target, self.grenade_timer))
            return True
        return False

    def throw_grenade(self, unit: Unit, target: Point2):
        unit(AbilityId.KD8CHARGE_KD8CHARGE, target)
        self.unconfirmed_grenade_throwers.append(unit.tag)

    async def grenade_available(self, unit: Unit) -> bool:
        if unit.tag in self.unconfirmed_grenade_throwers:
            try:
                available = await self.bot.can_cast(unit, AbilityId.KD8CHARGE_KD8CHARGE, only_check_energy_and_cooldown=True)
            except ProtocolError:
                # game ended
                return False
            if not available:
                self.unconfirmed_grenade_throwers.remove(unit.tag)
                self.grenade_cooldowns[unit.tag] = self.bot.time + self.grenade_cooldown
        elif unit.tag not in self.grenade_cooldowns:
            return True
        elif self.grenade_cooldowns[unit.tag] < self.bot.time:
            del self.grenade_cooldowns[unit.tag]
            return True
        return False
