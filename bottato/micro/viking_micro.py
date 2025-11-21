from __future__ import annotations
from typing import List, Dict

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.units import Units

from bottato.unit_types import UnitTypes
from bottato.mixins import GeometryMixin
from bottato.micro.base_unit_micro import BaseUnitMicro


class VikingMicro(BaseUnitMicro, GeometryMixin):
    ability_health = 0.55
    last_enemies_in_range_update: float = 0
    target_assignments: dict[int, Unit] = {}  # viking tag -> enemy tag
    attack_health = 0.4

    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if unit.tag in self.scout_tags:
            # scout mode, don't land
            return False
        if unit.is_flying:
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
                    nearest_distance = unit.distance_to(nearest_enemy)
                    if nearest_enemy.type_id == UnitTypeId.SIEGETANKSIEGED:
                        if nearest_distance > 1.8:
                            unit.move(nearest_enemy.position)
                        elif nearest_distance < 1.1:
                            unit.move(nearest_enemy.position.towards(unit, 1.5)) # type: ignore
                        else:
                            unit(AbilityId.MORPH_VIKINGASSAULTMODE)
                        return True
                    if self.bot.enemy_structures:
                        nearest_structure = self.bot.enemy_structures.closest_to(unit)
                        nearest_distance = min(nearest_distance, unit.distance_to(nearest_structure))
                    if nearest_distance < 11:
                        # wait to land until closer to enemies
                        unit(AbilityId.MORPH_VIKINGASSAULTMODE)
                        return True
            elif len(nearby_enemies) < 4:
                # land if hurt and getting chased down by a faster unit
                aerial_threats = nearby_enemies.filter(lambda u: UnitTypes.can_attack_air(u)
                                                       and not UnitTypes.can_attack_ground(u)
                                                       and u.movement_speed > unit.movement_speed)
                if aerial_threats:
                    unit(AbilityId.MORPH_VIKINGASSAULTMODE)
                    return True
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
                        return True
            if not nearby_enemies:
                nearby_enemies = self.bot.enemy_structures.closer_than(10, unit).filter(
                    lambda u: self.bot.get_terrain_height(u) <= self.bot.get_terrain_height(unit))
            else:
                anti_air_structures = nearby_enemies.filter(lambda u: u.type_id in (UnitTypeId.MISSILETURRET, UnitTypeId.SPORECRAWLER))
                if anti_air_structures and anti_air_structures.closest_distance_to(unit) <= 8:
                    # don't take off near anti-air turrets
                    return False
            if not nearby_enemies or len(nearby_enemies.filter(lambda u: (u.is_flying or u.type_id == UnitTypeId.COLOSSUS) and UnitTypes.can_attack(u))) > 0:
                # take off if no enemies or any fliers nearby
                unit(AbilityId.MORPH_VIKINGFIGHTERMODE)
                return True
            enemy_tanks = nearby_enemies.filter(lambda u: u.type_id == UnitTypeId.SIEGETANKSIEGED)
            if enemy_tanks:
                unit.attack(enemy_tanks.first)
                return True
        return False

    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        if force_move:
            return False
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        if unit.is_flying and unit.health_percentage < health_threshold:
            return False

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
                if not viking.is_flying:
                    continue
                enemies = UnitTypes.in_attack_range_of(viking, self.bot.enemy_units, bonus_distance=5).filter(
                    lambda unit: unit.can_be_attacked)
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
            return True

        bonus_distance = 2 if unit.is_flying else 4
        enemies = self.bot.enemy_units.filter(lambda unit: unit.can_be_attacked and unit.armor < 10)
        if not unit.is_flying:
            enemies += self.bot.enemy_structures.of_type(UnitTypes.OFFENSIVE_STRUCTURE_TYPES)
        candidates = UnitTypes.in_attack_range_of(unit, enemies, bonus_distance)
        if not candidates and not unit.is_flying:
            candidates = UnitTypes.in_attack_range_of(unit, self.bot.enemy_structures, bonus_distance)
        if not candidates:
            return False

        if can_attack:
            closest_target = candidates.closest_to(unit)
            return self._kite(unit, closest_target)

        return self._stay_at_max_range(unit, candidates)
