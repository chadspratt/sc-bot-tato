from __future__ import annotations
from typing import List, Dict

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.enums import UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.unit_types import UnitTypes


class VikingMicro(BaseUnitMicro, GeometryMixin):
    ability_health = 0.55
    last_enemies_in_range_update: float = 0
    target_assignments: dict[int, Unit] = {}  # viking tag -> enemy tag
    attack_health = 0.4

    @timed_async
    async def move(self, unit: Unit, target: Point2, force_move: bool = False, previous_position: Point2 | None = None) -> UnitMicroType:
        enemy_bcs = self.bot.enemy_units.of_type(UnitTypeId.BATTLECRUISER)
        if enemy_bcs:
            return await self.scout(unit, enemy_bcs.closest_to(unit).position)
        return await super().move(unit, target, force_move, previous_position)

    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> UnitMicroType:
        if unit.tag in self.scout_tags:
            # scout mode, don't land
            return UnitMicroType.NONE
        if unit.is_flying:
            viking_count = self.bot.units.of_type(UnitTypeId.VIKINGFIGHTER).amount
            if viking_count < 4:
                # don't land if we have few vikings
                return UnitMicroType.NONE
            nearby_enemies = self.bot.enemy_units.closer_than(25, unit) \
                + self.bot.enemy_structures.of_type(UnitTypes.OFFENSIVE_STRUCTURE_TYPES).closer_than(25, unit)
            if unit.health_percentage >= health_threshold:
                # don't land if there are air targets nearby
                if not nearby_enemies:
                    nearby_enemies = self.bot.enemy_structures.closer_than(10, unit).filter(
                        lambda u: self.bot.get_terrain_height(u) <= self.bot.get_terrain_height(unit))
                if nearby_enemies and len(nearby_enemies.filter(lambda u: u.is_flying or u.type_id == UnitTypeId.COLOSSUS)) == 0:
                    # land on enemy sieged tanks
                    nearest_enemy = nearby_enemies.closest_to(unit)
                    nearest_distance_sq = unit.distance_to_squared(nearest_enemy)
                    if nearest_enemy.type_id == UnitTypeId.SIEGETANKSIEGED:
                        if nearest_distance_sq > 3.24:
                            unit.move(self.map.get_pathable_position(nearest_enemy.position, unit))
                        elif nearest_distance_sq < 1.21:
                            unit.move(self.map.get_pathable_position(nearest_enemy.position.towards(unit, 1.5), unit))
                        else:
                            unit(AbilityId.MORPH_VIKINGASSAULTMODE)
                        return UnitMicroType.USE_ABILITY
                    if self.bot.enemy_structures:
                        nearest_structure = self.bot.enemy_structures.closest_to(unit)
                        nearest_distance_sq = min(nearest_distance_sq, unit.distance_to_squared(nearest_structure))
                    if nearest_distance_sq < 144:
                        # wait to land until closer to enemies
                        unit(AbilityId.MORPH_VIKINGASSAULTMODE)
                        return UnitMicroType.USE_ABILITY
            elif len(nearby_enemies) < 4:
                # land if hurt and getting chased down by a faster unit
                aerial_threats = nearby_enemies.filter(lambda u: UnitTypes.can_attack_air(u)
                                                       and not UnitTypes.can_attack_ground(u)
                                                       and u.movement_speed > unit.movement_speed)
                if aerial_threats:
                    unit(AbilityId.MORPH_VIKINGASSAULTMODE)
                    return UnitMicroType.USE_ABILITY
        else:
            nearby_enemies = self.bot.enemy_units.closer_than(27, unit) \
                + self.bot.enemy_structures.of_type(UnitTypes.OFFENSIVE_STRUCTURE_TYPES).closer_than(27, unit)
            if unit.health_percentage < health_threshold:
                aerial_threats = nearby_enemies.filter(lambda u: UnitTypes.can_attack_air(u)
                                                       and not UnitTypes.can_attack_ground(u))
                if not aerial_threats:
                    ground_threats = nearby_enemies.filter(lambda u: UnitTypes.can_attack_ground(u)
                                                        and not UnitTypes.can_attack_air(u))
                    if ground_threats:
                        unit(AbilityId.MORPH_VIKINGFIGHTERMODE)
                        return UnitMicroType.USE_ABILITY
            if not nearby_enemies:
                nearby_enemies = self.bot.enemy_structures.closer_than(10, unit).filter(
                    lambda u: self.bot.get_terrain_height(u) <= self.bot.get_terrain_height(unit))
            else:
                anti_air_structures = nearby_enemies.filter(lambda u: u.type_id in (UnitTypeId.MISSILETURRET, UnitTypeId.SPORECRAWLER))
                if anti_air_structures and anti_air_structures.closest_distance_to(unit) <= 8:
                    # don't take off near anti-air turrets
                    return UnitMicroType.NONE
            if not nearby_enemies or len(nearby_enemies.filter(lambda u: (u.is_flying or u.type_id == UnitTypeId.COLOSSUS) and UnitTypes.can_attack(u))) > 0:
                # take off if no enemies or any fliers nearby
                unit(AbilityId.MORPH_VIKINGFIGHTERMODE)
                return UnitMicroType.USE_ABILITY
            enemy_tanks = nearby_enemies.filter(lambda u: u.type_id == UnitTypeId.SIEGETANKSIEGED)
            if enemy_tanks:
                unit.attack(enemy_tanks.first)
                return UnitMicroType.ATTACK
        return UnitMicroType.NONE

    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> UnitMicroType:
        if force_move:
            return UnitMicroType.NONE
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE
        if unit.is_flying and unit.health_percentage < health_threshold:
            return UnitMicroType.NONE

        if self.last_enemies_in_range_update != self.bot.time:
            # update targets once per frame
            self.last_enemies_in_range_update = self.bot.time
            enemies_in_range: dict[int, List[Unit]] = {}
            self.target_assignments.clear()
            vikings = self.bot.units.filter(lambda unit: unit.type_id == UnitTypeId.VIKINGFIGHTER
                                            and unit.is_flying and unit.health_percentage >= health_threshold)
            other_type_friendlies: Dict[int, Units] = {}
            # make lists of vikings that can attack each enemy
            damage_vs_type: dict[UnitTypeId, float] = {}
            for viking in vikings:
                enemies = self.enemy.in_friendly_attack_range(viking, attack_range_buffer=5)
                enemies.sort(key=lambda e: e.health + e.shield)
                for enemy in enemies:
                    if enemy.type_id not in damage_vs_type:
                        damage_vs_type[enemy.type_id] = viking.calculate_damage_vs_target(enemy)[0]
                    if enemy.tag not in enemies_in_range:
                        enemies_in_range[enemy.tag] = []
                    enemies_in_range[enemy.tag].append(viking)
                other_type_friendlies[viking.tag] = self.bot.units.exclude_type(UnitTypeId.VIKINGFIGHTER).closer_than(4, viking)

            # for each enemy compare number of vikings that can attack it to number of nearby threats of same type
            # also compare number of other allies to number of threats of other types
            for enemy_tag, vikings in enemies_in_range.items():
                enemy_unit = self.bot.enemy_units.find_by_tag(enemy_tag)
                if not enemy_unit:
                    continue
                other_nearby_threats = self.bot.enemy_units.closer_than(4, enemy_unit).filter(
                    lambda unit: UnitTypes.can_attack_air(unit) and unit.tag != enemy_tag)
                same_type_threats = other_nearby_threats.of_type(enemy_unit.type_id)
                # other_type_threats = other_nearby_threats.exclude_type(enemy_unit.type_id)
                enemy_health = enemy_unit.health + enemy_unit.shield
                if len(vikings) >= len(same_type_threats):
                    # do_attack = False
                    # check if any viking would attack this target
                    # for viking in vikings:
                    #     if len(other_type_friendlies[viking.tag]) >= len(other_type_threats):
                    #         if viking.tag in self.target_assignments:
                    #             continue
                    #         do_attack = True
                    #         break
                    # if do_attack:
                    # if at least one will attack, commit all available to this target
                    for viking in vikings:
                        if viking.tag in self.target_assignments:
                            continue
                        self.target_assignments[viking.tag] = enemy_unit
                        enemy_health -= damage_vs_type[enemy_unit.type_id]
                        if enemy_health <= 0:
                            break

        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if can_attack and unit.tag in self.target_assignments:
            target = self.target_assignments[unit.tag]
            return self._kite(unit, target)

        if self._retreat_to_tank(unit, can_attack):
            return UnitMicroType.RETREAT

        attack_range_buffer = 2 if unit.is_flying else 4
        enemies = self.bot.enemy_units
        if not unit.is_flying:
            enemies += self.bot.enemy_structures.of_type(UnitTypes.OFFENSIVE_STRUCTURE_TYPES)
        candidates = self.enemy.in_attack_range(unit, enemies, attack_range_buffer)
        if not candidates:
            candidates = self.enemy.in_attack_range(unit, self.bot.enemy_structures, attack_range_buffer)
        if not candidates:
            return UnitMicroType.NONE

        if can_attack:
            closest_target = candidates.closest_to(unit)
            if closest_target.is_structure:
                unit.attack(closest_target)
                return UnitMicroType.ATTACK
            return self._kite(unit, closest_target)
        
        # try to shut down medivac drops
        if len(candidates) < 8 and candidates(UnitTypeId.MEDIVAC):
            unit.attack(candidates(UnitTypeId.MEDIVAC).first)
            return UnitMicroType.ATTACK
        return self._stay_at_max_range(unit, candidates)
