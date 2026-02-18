from __future__ import annotations

from socket import close
from typing import Dict, List, Tuple

from cython_extensions.geometry import cy_towards
from cython_extensions.units_utils import cy_center, cy_closer_than, cy_closest_to
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
    time_in_frames_to_attack = 0.5 * 22.4

    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, force_move: bool = False) -> UnitMicroType:
        if unit.tag in self.scout_tags:
            # scout mode, don't land
            return UnitMicroType.NONE
        nearby_range = 25 if unit.is_flying else 27
        nearby_enemies = Units(cy_closer_than(self.bot.enemy_units.exclude_type(UnitTypes.WORKER_TYPES), nearby_range, unit.position) +
                               cy_closer_than(self.bot.enemy_structures.of_type(UnitTypes.OFFENSIVE_STRUCTURE_TYPES), nearby_range, unit.position),
                               bot_object=self.bot)
        if unit.is_flying:
            viking_count = self.bot.units.of_type(UnitTypeId.VIKINGFIGHTER).amount
            if viking_count < 4:
                # don't land if we have few vikings
                return UnitMicroType.NONE
            if unit.health_percentage >= self.ability_health:
                # don't land if there are air targets nearby
                if not nearby_enemies:
                    nearby_enemies = Units(cy_closer_than(self.bot.enemy_structures, 10, unit.position), bot_object=self.bot).filter(
                        lambda u: self.bot.get_terrain_height(u) <= self.bot.get_terrain_height(unit))
                if nearby_enemies and len(nearby_enemies.filter(lambda u: u.is_flying or u.type_id == UnitTypeId.COLOSSUS)) == 0:
                    # land on enemy sieged tanks
                    nearest_enemy = cy_closest_to(unit.position, nearby_enemies)
                    nearest_distance_sq = unit.distance_to_squared(nearest_enemy)
                    if nearest_enemy.type_id == UnitTypeId.SIEGETANKSIEGED:
                        if nearest_distance_sq > 3.24:
                            unit.move(self.map.get_pathable_position(nearest_enemy.position, unit))
                        elif nearest_distance_sq < 1.21:
                            unit.move(self.map.get_pathable_position(Point2(cy_towards(nearest_enemy.position, unit.position, 1.5)), unit))
                        else:
                            unit(AbilityId.MORPH_VIKINGASSAULTMODE)
                        return UnitMicroType.USE_ABILITY
                    if self.bot.enemy_structures:
                        nearest_structure = cy_closest_to(unit.position, self.bot.enemy_structures)
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
            if unit.health_percentage < self.ability_health:
                aerial_threats = nearby_enemies.filter(lambda u: UnitTypes.can_attack_air(u)
                                                       and not UnitTypes.can_attack_ground(u))
                if not aerial_threats:
                    unit(AbilityId.MORPH_VIKINGFIGHTERMODE)
                    return UnitMicroType.USE_ABILITY
                ground_threats = nearby_enemies.filter(lambda u: UnitTypes.can_attack_ground(u)
                                                    and not UnitTypes.can_attack_air(u))
                if not ground_threats:
                    return UnitMicroType.NONE
            if not nearby_enemies:
                nearby_enemies = Units(cy_closer_than(self.bot.enemy_structures, 10, unit.position), bot_object=self.bot).filter(
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
    def _attack_something(self, unit: Unit, health_threshold: float, move_position: Point2, force_move: bool = False) -> UnitMicroType:
        if force_move:
            return UnitMicroType.NONE
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE
        # below retreat_health: do nothing
        if unit.is_flying and unit.health_percentage < self.retreat_health:
            return UnitMicroType.NONE

        if self.last_enemies_in_range_update != self.bot.time:
            # update targets once per frame
            self.last_enemies_in_range_update = self.bot.time
            defenders_in_range: dict[int, List[Unit]] = {}
            all_enemies: Dict[int, Unit] = {}
            self.target_assignments.clear()
            vikings = self.bot.units.filter(lambda unit: unit.type_id == UnitTypeId.VIKINGFIGHTER
                                            and unit.is_flying and unit.health_percentage >= health_threshold)
            other_type_friendlies: Dict[int, Units] = {}
            # make lists of vikings that can attack each enemy
            damage_vs_type: dict[UnitTypeId, float] = {}
            closest_counts: dict[int, int] = {}
            for defender in vikings:
                enemies = self.enemy.in_friendly_attack_range(defender, attack_range_buffer=5)
                closest_enemy: Unit | None = None
                closest_distance: float = float('inf')
                for enemy in enemies:
                    all_enemies[enemy.tag] = enemy
                    if enemy.type_id not in damage_vs_type:
                        damage_vs_type[enemy.type_id] = defender.calculate_damage_vs_target(enemy)[0]
                    if enemy.tag not in defenders_in_range:
                        defenders_in_range[enemy.tag] = []
                    enemy_distance = defender.distance_to_squared(enemy)
                    if enemy_distance < closest_distance:
                        closest_distance = enemy_distance
                        closest_enemy = enemy   
                    defenders_in_range[enemy.tag].append(defender)
                if closest_enemy:
                    closest_counts[closest_enemy.tag] = closest_counts.get(closest_enemy.tag, 0) + 1
                other_type_friendlies[defender.tag] = Units(cy_closer_than(self.bot.units.exclude_type(UnitTypeId.VIKINGFIGHTER), 4, defender.position), bot_object=self.bot)

            # sort enemies by how many vikings have them as closest
            # enemies.sort(key=lambda e: e.health + e.shield)
            def enemy_sort_key(enemy_tag: int) -> float:
                enemy_unit = all_enemies[enemy_tag]
                return enemy_unit.health + enemy_unit.shield - damage_vs_type[enemy_unit.type_id] * closest_counts.get(enemy_tag, 0)
            enemy_order = sorted(defenders_in_range.keys(), key=enemy_sort_key)

            # for each enemy compare number of vikings that can attack it to number of nearby threats of same type
            for enemy_tag in enemy_order:
                defenders = defenders_in_range[enemy_tag]
                enemy_unit = all_enemies.get(enemy_tag)
                if enemy_unit is None:
                    continue
                other_nearby_threats = Units(cy_closer_than(self.bot.enemy_units, 4, enemy_unit.position), bot_object=self.bot).filter(
                    lambda unit: UnitTypes.can_attack_air(unit) and unit.tag != enemy_tag)
                # enemy_type = enemy_unit.type_id
                # same_type_threats = self.bot.enemy_units.filter(lambda u:
                #                                                 UnitTypes.can_attack_air(u)
                #                                                 and u.tag != enemy_tag
                #                                                 and u.type_id == enemy_type)
                # other_type_threats = other_nearby_threats.exclude_type(enemy_unit.type_id)
                if len(other_nearby_threats) <= len(defenders) * 3 or UnitTypes.range_vs_target(defenders[0], enemy_unit) > UnitTypes.range_vs_target(enemy_unit, defenders[0]):
                    enemy_health = enemy_unit.health + enemy_unit.shield
                    for defender in defenders:
                        if defender.tag in self.target_assignments:
                            continue
                        self.target_assignments[defender.tag] = enemy_unit
                        enemy_health -= damage_vs_type[enemy_unit.type_id]
                        if enemy_health <= -10:
                            break

        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if can_attack and unit.tag in self.target_assignments:
            target = self.target_assignments[unit.tag]
            if target.air_range >= unit.air_range:
                unit.attack(target)
                return UnitMicroType.ATTACK
            else:
                threats = self.enemy.threats_to_friendly_unit(unit, 2)
                threats.append(target)
                return self._kite(unit, threats)

        enemies = self.bot.enemy_units + self.bot.enemy_structures.of_type(UnitTypes.OFFENSIVE_STRUCTURE_TYPES)
        attack_range_buffer = 2 if unit.is_flying else 4
        candidates = self.enemy.in_attack_range(unit, enemies, attack_range_buffer)
        if not candidates:
            candidates = self.enemy.in_attack_range(unit, self.bot.enemy_structures, attack_range_buffer)

        if not candidates:
            return UnitMicroType.NONE

        if self._retreat_to_better_unit(unit, can_attack):
            return UnitMicroType.RETREAT

        # below attack_health: if threats and no target in range, do nothing
        if unit.is_flying and unit.health_percentage < health_threshold:
            if self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6, first_only=True):
                return UnitMicroType.NONE

        if can_attack and not unit.is_flying:
            # stick to assigned targets for flying but landed can target normally
            closest_target = cy_closest_to(unit.position, candidates)
            if closest_target.is_structure:
                unit.attack(closest_target)
                return UnitMicroType.ATTACK
            return self._kite(unit, candidates)

        return self._stay_at_max_range(unit, candidates)
    
    # copied from banshee micro
    @timed
    def _harass_attack_something(self, unit, health_threshold, harass_location: Point2, force_move: bool = False) -> UnitMicroType:
        # below harass_retreat_health: do nothing
        if unit.health_percentage <= self.harass_retreat_health:
            return UnitMicroType.NONE
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if force_move and not can_attack:
            return UnitMicroType.NONE
        nearby_enemies: Units
        attack_range_buffer = 0 if can_attack or unit.health_percentage <= self.harass_retreat_health else 5

        enemy_candidates = self.enemy.get_candidates(include_structures=False, include_out_of_view=False).sorted(lambda u: u.health + u.shield)
        nearby_enemies = self.enemy.in_attack_range(unit, enemy_candidates, attack_range_buffer, first_only=True)
        if not nearby_enemies and attack_range_buffer == 0:
            nearby_enemies = self.enemy.in_attack_range(unit, enemy_candidates, 5, first_only=True)

        # exclude enemies that are too close to anti-air structures
        anti_air_structures = self.bot.enemy_structures.filter(
            lambda s: s.type_id in UnitTypes.ANTI_AIR_STRUCTURE_TYPES and s.is_ready)
        if anti_air_structures:
            nearby_enemies = nearby_enemies.filter(lambda e: self.closest_distance_squared(e, anti_air_structures) > 36)

        if UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_recent_enemies()):
            threat_range_buffer = 3 if nearby_enemies and can_attack and unit.health_percentage > self.harass_retreat_health else 5
            threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=threat_range_buffer)
            if threats:
                # below harass_attack_health: if threats and no target in range, do nothing
                if unit.health_percentage < self.harass_attack_health and not nearby_enemies:
                    return UnitMicroType.NONE
                for threat in threats:
                    if threat.is_structure and self.enemy.safe_distance_squared(unit, threat) > self.enemy.get_attack_range_with_buffer_squared(threat, unit, 3):
                        continue
                    if not threat.is_flying or UnitTypes.air_range(threat) >= unit.air_range:
                        # don't attack enemies that outrange
                        unit.move(self.get_circle_around_position(unit, Point2(cy_center(threats)), harass_location))
                        return UnitMicroType.MOVE

        if nearby_enemies:
            return self._kite(unit, nearby_enemies)
        if force_move:
            return UnitMicroType.NONE
        # if can_attack:
        #     enemy_structures = self.bot.enemy_structures.sorted(lambda u: u.health + u.shield)
        #     nearby_enemy = self.enemy.in_attack_range(unit, enemy_structures, attack_range_buffer, first_only=True)
        #     if nearby_enemy:
        #         self._attack(unit, nearby_enemy.first)
        #         return UnitMicroType.ATTACK
        if unit.tag in self.harass_location_reached_tags:
            nearest_workers = self.enemy.get_closest_targets(unit, included_types=UnitTypes.WORKER_TYPES)
            if anti_air_structures:
                nearest_workers = nearest_workers.filter(lambda u: not self.unit_is_closer_than(u, anti_air_structures, 6))
            if nearest_workers:
                target = sorted(nearest_workers, key=lambda t: t.health + t.shield)[0]
                self._attack(unit, target)
                return UnitMicroType.ATTACK
        return UnitMicroType.NONE
