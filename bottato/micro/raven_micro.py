from __future__ import annotations
from loguru import logger

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

from .base_unit_micro import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class RavenMicro(BaseUnitMicro, GeometryMixin):
    turret_drop_range = 2
    turret_attack_range = 6
    ideal_enemy_distance = turret_drop_range + turret_attack_range - 1
    # XXX use shorter range if enemy unit is facing away from raven, likely fleeing
    turret_energy_cost = 50
    ability_health = 0.6
    turret_drop_time = 1.5

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        excluded_types = [UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.DRONE, UnitTypeId.PROBE, UnitTypeId.OVERLORD, UnitTypeId.OVERSEER, UnitTypeId.EGG, UnitTypeId.LARVA]
        enemy_unit, enemy_distance = self.enemy.get_closest_target(unit, distance_limit=20, include_structures=False, include_destructables=False, include_out_of_view=False, excluded_types=excluded_types)
        threats = self.enemy.threats_to(unit)
        logger.debug(f"raven {unit} closest unit {enemy_unit}({enemy_distance}), energy={unit.energy}")
        if enemy_unit is None:
            return False
        elif threats and enemy_distance < self.ideal_enemy_distance - 2:
            logger.debug(f"{unit} too close to {enemy_unit} ({enemy_distance})")
            # unit.move(enemy_unit.position.towards(unit, self.ideal_enemy_distance))
            # too close
            return False
        if enemy_unit.type_id == UnitTypeId.SIEGETANKSIEGED:
            # don't try to attack sieged tanks
            return self.drop_turret(unit, enemy_unit.position.towards(unit, enemy_unit.radius + 1))
        return self.attack_with_turret(unit, self.enemy.get_predicted_position(enemy_unit, self.turret_drop_time))

    def attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        # doesn't have an auto attack
        return False

    def attack_with_turret(self, unit: Unit, target: Point2):
        if self.turret_available(unit):
            self.bot.client.debug_line_out(unit, self.convert_point2_to_3(target), (100, 255, 50))
            turret_position = target.towards(unit, self.turret_attack_range - 1, limit=True)
            self.drop_turret(unit, turret_position)
            logger.debug(f"{unit} trying to drop turret at {turret_position} to attack {target} at {target.position}")
            return True

        return False

    def drop_turret(self, unit: Unit, target: Point2):
        unit(AbilityId.BUILDAUTOTURRET_AUTOTURRET, target)

    def fire_missile(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_ANTIARMORMISSILE, target)

    def interfere(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_INTERFERENCEMATRIX, target)

    def turret_available(self, unit: Unit) -> bool:
        return unit.energy >= self.turret_energy_cost
