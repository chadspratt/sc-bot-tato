from __future__ import annotations
from loguru import logger

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

from bottato.unit_types import UnitTypes
from bottato.mixins import GeometryMixin
from bottato.micro.base_unit_micro import BaseUnitMicro


class RavenMicro(BaseUnitMicro, GeometryMixin):
    turret_drop_range = 2
    turret_attack_range = 6
    ideal_enemy_distance = turret_drop_range + turret_attack_range - 1
    # XXX use shorter range if enemy unit is facing away from raven, likely fleeing
    turret_energy_cost = 50
    ability_health = 0.6
    attack_health = 0.7
    turret_drop_time = 1.5
    missing_hidden_units: set[int] = set()

    async def use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if force_move:
            return False
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
            return await self.drop_turret(unit, enemy_unit.position.towards(unit, enemy_unit.radius + 1))
        return await self.attack_with_turret(unit, self.enemy.get_predicted_position(enemy_unit, self.turret_drop_time))

    def attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        if unit.health_percentage < health_threshold:
            return False
        # stay safe
        threats = self.bot.enemy_units.filter(lambda enemy: UnitTypes.can_attack_air(enemy))
        if threats:
            nearest_threat = threats.closest_to(unit)
            if nearest_threat.distance_to(unit) < unit.sight_range:
                target_position = nearest_threat.position.towards(unit, unit.sight_range - 1)
                unit.move(target_position)
                return True
        # provide detection
        need_detection = self.enemy.enemies_needing_detection()
        for enemy in need_detection:
            if enemy.age == 0:
                self.missing_hidden_units.discard(enemy.tag)
        need_detection = need_detection.filter(lambda enemy: enemy.tag not in self.missing_hidden_units)
        if need_detection:
            closest_unit: Unit = self.closest_unit_to_unit(unit, need_detection)
            if self.distance(closest_unit, unit) > unit.sight_range:
                target_position = closest_unit.position.towards(unit, unit.sight_range - 1)
                unit.move(target_position)
                return True
            elif self.bot.is_visible(closest_unit.position) and closest_unit.age > 0:
                self.missing_hidden_units.add(closest_unit.tag)
        return False

    async def attack_with_turret(self, unit: Unit, target: Point2):
        if self.turret_available(unit):
            self.bot.client.debug_line_out(unit, self.convert_point2_to_3(target), (100, 255, 50))
            turret_position = target.towards(unit, self.turret_attack_range - 1, limit=True)
            await self.drop_turret(unit, turret_position)
            logger.debug(f"{unit} trying to drop turret at {turret_position} to attack {target} at {target.position}")
            return True

        return False

    async def drop_turret(self, unit: Unit, target: Point2):
        position = await self.bot.find_placement(UnitTypeId.AUTOTURRET, target, placement_step=1, max_distance=2)
        if position:
            unit(AbilityId.BUILDAUTOTURRET_AUTOTURRET, position)
            return True
        return False

    def fire_missile(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_ANTIARMORMISSILE, target)

    def interfere(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_INTERFERENCEMATRIX, target)

    def turret_available(self, unit: Unit) -> bool:
        return unit.energy >= self.turret_energy_cost
