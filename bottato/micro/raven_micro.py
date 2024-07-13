from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from .base_unit_micro import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class RavenMicro(BaseUnitMicro, GeometryMixin):
    grenade_cooldown = 14.0
    grenade_timer = 1.7

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        return self.attack_with_turret(unit, enemy.threats_to(unit))

    def attack_with_turret(self, unit: Unit, targets: Units):
        logger.info(f"{unit} trying to drop turret on {targets}")
        if targets and self.turret_available(unit):
            turret_position = unit.position.towards(targets.center, 2, limit=True)
            self.drop_turret(unit, turret_position)
            logger.info(f"{unit} dropped turret at {turret_position}")
            return True

        return False

    def drop_turret(self, unit: Unit, target: Unit):
        unit(AbilityId.BUILDAUTOTURRET_AUTOTURRET, target)

    def fire_missile(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_ANTIARMORMISSILE, target)

    def interfere(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_INTERFERENCEMATRIX, target)

    def turret_available(self, unit: Unit) -> bool:
        return unit.energy > 50
