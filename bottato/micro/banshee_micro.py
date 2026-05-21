from __future__ import annotations

from cython_extensions.units_utils import cy_center
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.enums import UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.unit_types import UnitTypes


class BansheeMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.65
    harass_attack_health: float = 0.8
    harass_retreat_health: float = 0.6
    retreat_health: float = 0.6
    cloak_researched: bool = False
    cloak_energy_threshold: float = 40.0

    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, force_move: bool = False) -> UnitMicroType:
        if not self.cloak_researched:
            if UpgradeId.BANSHEECLOAK in self.bot.state.upgrades:
                self.cloak_researched = True
            else:
                return UnitMicroType.NONE
        if not unit.is_cloaked:
            threats = self.tactics.enemy.get_recent_enemies().filter(
                lambda u: not u.is_detector)
            if unit.energy >= self.cloak_energy_threshold and self.tactics.enemy.threats_to(unit, threats, 2):
                unit(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
                return UnitMicroType.USE_ABILITY
        else:
            if not self.tactics.enemy.threats_to_friendly_unit(unit, attack_range_buffer=10).exists:
                unit(AbilityId.BEHAVIOR_CLOAKOFF_BANSHEE)
                return UnitMicroType.USE_ABILITY
        return UnitMicroType.NONE
    
    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, move_position: Point2, force_move: bool = False) -> UnitMicroType:
        # below retreat_health: do nothing
        if unit.health_percentage <= self.retreat_health:
            return UnitMicroType.NONE
        if self.tactics.enemy.can_be_attacked(unit, self.tactics.enemy.get_recent_enemies()) \
                and unit.health_percentage < self.attack_health \
                and self.tactics.enemy.threats_to_friendly_unit(unit, attack_range_buffer=3):
            return UnitMicroType.NONE
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if force_move and not can_attack:
            return UnitMicroType.NONE
        attack_range_buffer = 0 if can_attack else 5
        target_candidates = self.get_target_candidates(unit)
        if target_candidates and can_attack:
            return self._kite(unit, target_candidates)

        if force_move:
            return UnitMicroType.NONE
        nearest_priority, nearest_priority_distance = self.tactics.enemy.get_closest_target(unit, included_types=UnitTypes.get_priority_target_types(unit))
        maximum_hunting_distance = 150
        if nearest_priority and nearest_priority_distance < maximum_hunting_distance:
            return self._kite(unit, nearest_priority)
        if self.cloak_researched and self.bot.enemy_units((UnitTypeId.OBSERVER, UnitTypeId.OVERSEER, UnitTypeId.RAVEN)).amount == 0:
            nearest_enemy, enemy_distance = self.tactics.enemy.get_closest_target(unit, include_structures=False)
            if nearest_enemy and enemy_distance < 20 and can_attack:
                return self._kite(unit, nearest_enemy)
        return UnitMicroType.NONE
    
    def get_target_candidates(self, unit: Unit) -> Units:
        # try to snipe structures that just started and shut down in-progress anti-air
        incomplete_structures = self.bot.enemy_structures.filter(
            lambda s: not s.is_ready
                        and s.is_visible
                        and (s.type_id in UnitTypes.ANTI_AIR_STRUCTURE_TYPES or s.health + s.shield < 50)
            )
        excluded_types = set()
        if self.tactics.enemy.can_be_attacked(unit, self.tactics.enemy.get_recent_enemies()):
            excluded_types = UnitTypes.get_priority_avoidance_types(unit)
        enemy_candidates = self.tactics.enemy.get_candidates(include_structures=False,
                                                             include_out_of_view=False,
                                                             excluded_types=excluded_types)
        enemy_candidates.extend(incomplete_structures)
        return enemy_candidates

    @timed
    def _harass_attack_something(self, unit, health_threshold, harass_location: Point2, force_move: bool = False) -> UnitMicroType:
        # below harass_retreat_health: do nothing
        if unit.health_percentage <= self.harass_retreat_health:
            return UnitMicroType.NONE
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if force_move and not can_attack:
            return UnitMicroType.NONE

        enemy_candidates = self.get_target_candidates(unit)
        attack_range_buffer = 0 if can_attack or unit.health_percentage <= self.harass_retreat_health else 5
        targets: Units = self.tactics.enemy.in_attack_range(unit, enemy_candidates, attack_range_buffer)
        if not targets and attack_range_buffer == 0:
            targets = self.tactics.enemy.in_attack_range(unit, enemy_candidates, 5)
        
        if targets:
            return self._kite(unit, targets)

        if self.tactics.enemy.can_be_attacked(unit, self.tactics.enemy.get_recent_enemies()):
            threat_range_buffer = 3 if targets and can_attack and unit.health_percentage > self.harass_retreat_health else 5
            threats = self.tactics.enemy.threats_to_friendly_unit(unit, attack_range_buffer=threat_range_buffer, visible_only=not unit.is_cloaked)
            if threats:
                # below harass_attack_health: if threats and no target in range, do nothing
                if unit.health_percentage < self.harass_attack_health and not targets:
                    return UnitMicroType.NONE
                for threat in threats:
                    if not self.position_is_between(threat.position, unit.position, harass_location):
                        continue
                    if threat.is_structure and self.tactics.enemy.safe_distance_squared(unit, threat) > self.tactics.enemy.get_attack_range_with_buffer_squared(threat, unit, 3):
                        continue
                    if threat.is_flying or UnitTypes.air_range(threat) >= unit.ground_range:
                        # don't attack enemies that outrange
                        unit.move(self.get_circle_around_position(unit, Point2(cy_center(threats)), harass_location))
                        return UnitMicroType.MOVE
        if force_move:
            return UnitMicroType.NONE

        if unit.tag in self.harass_location_reached_tags:
            nearest_workers = self.tactics.enemy.get_closest_targets(unit, included_types=UnitTypes.WORKER_TYPES)
            if nearest_workers:
                targets = nearest_workers.sorted(key=lambda t: t.health + t.shield)
                self._kite(unit, targets)
                return UnitMicroType.ATTACK
        return UnitMicroType.NONE

    @timed_async
    async def _harass_retreat(self, unit: Unit, health_threshold: float, harass_location: Point2) -> UnitMicroType:
        # below harass_retreat_health: always retreat
        # below harass_attack_health: retreat if threats
        # above harass_attack_health: do nothing
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE

        # above harass_attack_health: do nothing
        if unit.health_percentage >= self.harass_attack_health:
            return UnitMicroType.NONE

        can_be_attacked = self.tactics.enemy.can_be_attacked(unit, self.tactics.enemy.get_recent_enemies())
        threats = self.tactics.enemy.threats_to_friendly_unit(unit, attack_range_buffer=5) if can_be_attacked else None
        is_below_attack_health = unit.health_percentage < self.harass_attack_health
        is_below_retreat_health = unit.health_percentage <= self.harass_retreat_health
        # check if incoming damage will bring unit below harass_retreat_health
        if not is_below_attack_health and threats:
            if not unit.health_max:
                # rare weirdness
                return UnitMicroType.RETREAT
            
            attack_threshold = unit.health_max * self.harass_attack_health
            current_health = unit.health
            for threat in threats:
                current_health -= threat.calculate_damage_vs_target(unit)[0]
                if current_health < attack_threshold:
                    is_below_attack_health = True
                    break

        # below harass_retreat_health: always retreat
        # below harass_attack_health: retreat if threats
        if threats or is_below_retreat_health:
            retreat_position = self._get_retreat_destination(unit, threats)
            unit.move(retreat_position)
            return UnitMicroType.RETREAT

        # not can_be_attacked and not below retreat: no need to retreat
        return UnitMicroType.NONE