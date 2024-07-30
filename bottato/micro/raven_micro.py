from __future__ import annotations
from loguru import logger
import random

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from .base_unit_micro import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class RavenMicro(BaseUnitMicro, GeometryMixin):
    turret_drop_range = 2

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        return self.attack_with_turret(unit, enemy.threats_to(unit))

    def attack_with_turret(self, unit: Unit, targets: Units):
        if targets and self.turret_available(unit):
            drop_distance = self.turret_drop_range * random.random()
            turret_position = unit.position.towards_with_random_angle(targets.center, drop_distance)
            turret_position = unit.position.towards(targets.center, 2, limit=True)
            self.drop_turret(unit, turret_position)
            logger.info(f"{unit} trying to drop turret at {turret_position}")
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
