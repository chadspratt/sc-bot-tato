from __future__ import annotations

from loguru import logger
from typing import Dict, Tuple

from cython_extensions.geometry import cy_distance_to, cy_towards
from cython_extensions.units_utils import cy_closest_to
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.enums import CustomEffectType, UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.custom_effect import CustomEffect
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.unit_types import UnitTypes


class RavenMicro(BaseUnitMicro, GeometryMixin):
    turret_drop_range = 2
    turret_attack_range = 6
    ideal_enemy_distance = turret_drop_range + turret_attack_range - 1
    turret_energy_cost = 50
    missile_energy_cost = 75
    ability_health = 0.6
    attack_health = 0.7 # detection
    turret_drop_time = 1.5
    missing_hidden_units: set[int] = set()
    last_missile_launch: Dict[int, Tuple[Unit, float, float, bool]] = {}

    excluded_types = [UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORBURROWED,
                      UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.DRONE, UnitTypeId.PROBE,
                      UnitTypeId.OVERLORD, UnitTypeId.OVERSEER,
                      UnitTypeId.EGG, UnitTypeId.LARVA,
                      UnitTypeId.ZERGLING, UnitTypeId.BROODLING]
                        
    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, force_move: bool = False) -> UnitMicroType:
        if unit.tag in self.last_missile_launch:
            enemy_unit, last_time, energy_before_launch, launch_detected = self.last_missile_launch[unit.tag]
            if self.bot.time - last_time < 11 and unit.energy < energy_before_launch and not launch_detected:
                BaseUnitMicro.add_custom_effect(CustomEffectType.ENEMY, enemy_unit, 3.5, self.bot.time, 3.0)
                self.last_missile_launch[unit.tag] = (enemy_unit, last_time, energy_before_launch, True)
        if unit.energy < self.turret_energy_cost:
            # not enough energy for cheapest spell
            return UnitMicroType.NONE
        
        military_units = self.bot.units.filter(lambda u: u.type_id not in self.excluded_types)
        nearby_friendly_units = military_units.filter(lambda u: u.type_id not in self.excluded_types and u.distance_to_squared(unit) < 100)
        
        if military_units.amount > 15 and nearby_friendly_units.amount <= 5 and unit.energy < 180 and unit.health_percentage >= 0.4:
            # save energy for supporting army
            return UnitMicroType.NONE
        
        if unit.energy >= self.missile_energy_cost and nearby_friendly_units.amount > 5:
            nearby_enemies = self.bot.enemy_units.filter(lambda enemy: enemy.type_id not in self.excluded_types and enemy.distance_to_squared(unit) < 225)
            if nearby_enemies:
                most_grouped_enemy, grouped_enemies = self.get_most_grouped_unit(nearby_enemies, self.bot, 3.5)
                if grouped_enemies.amount >= 5:
                    if self.fire_missile(unit, most_grouped_enemy):
                        return UnitMicroType.USE_ABILITY

        enemy_unit, enemy_distance = self.enemy.get_closest_target(unit, distance_limit=20, include_structures=False, include_destructables=False,
                                                                   include_out_of_view=False)
        if enemy_unit is None:
            return UnitMicroType.NONE

        threats = self.enemy.threats_to_friendly_unit(unit, 2)
        if threats and enemy_distance < self.ideal_enemy_distance - 2:
            # too close
            return UnitMicroType.NONE

        if enemy_unit.type_id == UnitTypeId.SIEGETANKSIEGED:
            return await self.drop_turret(unit, Point2(cy_towards(enemy_unit.position, unit.position, enemy_unit.radius + 1)))
        
        return await self.attack_with_turret(unit, self.enemy.get_predicted_position(enemy_unit, self.turret_drop_time))
        

    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, move_position: Point2, force_move: bool = False) -> UnitMicroType:
        if force_move:
            return UnitMicroType.NONE
        # below retreat_health: do nothing
        if unit.health_percentage < self.retreat_health:
            return UnitMicroType.NONE
        # stay safe
        threats = self.bot.enemy_units.filter(lambda enemy: UnitTypes.can_attack_air(enemy)) \
            + self.bot.enemy_structures.filter(lambda enemy: UnitTypes.can_attack_air(enemy))
        if threats:
            # below attack_health: if threats, do nothing
            if unit.health_percentage < health_threshold:
                return UnitMicroType.NONE
            nearest_threat = cy_closest_to(unit.position, threats)
            if nearest_threat.distance_to_squared(unit) < unit.sight_range ** 2:
                is_near_destination = move_position is not None and move_position._distance_squared(unit.position) < 9
                buffer = -1 if is_near_destination else 2
                target_position = Point2(cy_towards(nearest_threat.position, unit.position, unit.sight_range + buffer))
                unit.move(self.map.get_pathable_position(target_position, unit))
                return UnitMicroType.MOVE
        # provide detection
        need_detection = self.enemy.enemies_needing_detection()
        for enemy in need_detection:
            if enemy.age == 0:
                self.missing_hidden_units.discard(enemy.tag)
        need_detection = need_detection.filter(lambda enemy: enemy.tag not in self.missing_hidden_units)
        if need_detection:
            closest_unit: Unit = self.closest_unit_to_unit(unit, need_detection)
            closest_distance = self.distance(closest_unit, unit)
            if closest_distance < 30 and closest_distance > unit.sight_range:
                target_position = Point2(cy_towards(closest_unit.position, unit.position, unit.sight_range - 1))
                unit.move(self.map.get_pathable_position(target_position, unit))
                return UnitMicroType.MOVE
            elif self.bot.is_visible(closest_unit.position) and closest_unit.age > 0:
                self.missing_hidden_units.add(closest_unit.tag)
        return UnitMicroType.NONE

    @timed_async
    async def attack_with_turret(self, unit: Unit, target: Point2) -> UnitMicroType:
        self.bot.client.debug_line_out(unit, self.convert_point2_to_3(target, self.bot), (100, 255, 50))
        towards_distance = min(self.turret_drop_range - 1, cy_distance_to(target, unit.position))
        turret_position = Point2(cy_towards(target, unit.position, towards_distance))
        logger.debug(f"{unit} trying to drop turret at {turret_position} to attack {target} at {target.position}")
        return await self.drop_turret(unit, turret_position)

    @timed_async
    async def drop_turret(self, unit: Unit, target: Point2) -> UnitMicroType:
        position = await self.bot.find_placement(UnitTypeId.AUTOTURRET, target, placement_step=1, max_distance=2)
        if position:
            unit(AbilityId.BUILDAUTOTURRET_AUTOTURRET, position)
            return UnitMicroType.USE_ABILITY
        return UnitMicroType.NONE

    def fire_missile(self, unit: Unit, target: Unit) -> UnitMicroType:
        if unit.tag in self.last_missile_launch:
            _ , last_time, energy_before_launch, launch_detected = self.last_missile_launch[unit.tag]
            if self.bot.time - last_time < 11:
                if unit.energy < energy_before_launch:
                    # just launched a missile
                    return UnitMicroType.NONE
        self.last_missile_launch[unit.tag] = (target, self.bot.time, unit.energy, False)
        unit(AbilityId.EFFECT_ANTIARMORMISSILE, target)
        return UnitMicroType.USE_ABILITY

    def interfere(self, unit: Unit, target: Unit):
        unit(AbilityId.EFFECT_INTERFERENCEMATRIX, target)
