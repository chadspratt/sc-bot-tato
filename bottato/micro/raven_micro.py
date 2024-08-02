from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base_unit_micro import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class RavenMicro(BaseUnitMicro, GeometryMixin):
    turret_drop_range = 2
    turret_attack_range = 6
    ideal_enemy_distance = turret_drop_range + turret_attack_range - 1
    turret_energy_cost = 50

    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        enemy_unit, enemy_distance = enemy.get_closest_enemy(unit)
        if enemy_unit is None:
            return False
        elif enemy_distance < self.ideal_enemy_distance - 2:
            logger.info(f"{unit} too close to {enemy_unit} ({enemy_distance})")
            # unit.move(enemy_unit.position.towards(unit, self.ideal_enemy_distance))
            # too close
            return False
        return self.attack_with_turret(unit, enemy_unit)

    def attack_something(self, unit: Unit) -> bool:
        # doesn't have an auto attack
        return False

    def attack_with_turret(self, unit: Unit, target: Unit):
        if self.turret_available(unit):
            turret_position = target.position.towards(unit, self.turret_attack_range - 1, limit=True)
            self.drop_turret(unit, turret_position)
            logger.info(f"{unit} trying to drop turret at {turret_position} to attack {target} at {target.position}")
            return True

        return False

    def drop_turret(self, unit: Unit, target: Unit):
        unit(AbilityId.BUILDAUTOTURRET_AUTOTURRET, target)

    def fire_missile(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_ANTIARMORMISSILE, target)

    def interfere(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_INTERFERENCEMATRIX, target)

    def turret_available(self, unit: Unit) -> bool:
        return unit.energy >= self.turret_energy_cost
