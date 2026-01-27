from __future__ import annotations

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

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
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> UnitMicroType:
        if not self.cloak_researched:
            if UpgradeId.BANSHEECLOAK in self.bot.state.upgrades:
                self.cloak_researched = True
            else:
                return UnitMicroType.NONE
        if not unit.is_cloaked:
            threats = self.enemy.get_enemies().filter(
                lambda u: not u.is_detector)
            if unit.energy >= self.cloak_energy_threshold and self.enemy.threats_to(unit, threats, 2):
                unit(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
                return UnitMicroType.USE_ABILITY
        else:
            if unit.health_percentage < self.harass_attack_health and not self.unit_is_closer_than(unit, self.enemy.get_enemies(), 15):
                unit(AbilityId.BEHAVIOR_CLOAKOFF_BANSHEE)
                return UnitMicroType.USE_ABILITY
        return UnitMicroType.NONE
    
    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> UnitMicroType:
        if unit.health_percentage <= self.retreat_health:
            return UnitMicroType.NONE
        if UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies()) \
                and unit.health_percentage < self.attack_health \
                and self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=3):
            return UnitMicroType.NONE
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if force_move and not can_attack:
            return UnitMicroType.NONE
        attack_range_buffer = 0 if can_attack else 5
        enemy_candidates = self.enemy.get_candidates(include_out_of_view=False).sorted(lambda u: u.health + u.shield)
        attack_target = self._get_attack_target(unit, enemy_candidates, attack_range_buffer)
        if attack_target:
            return self._kite(unit, Units([attack_target], bot_object=self.bot))

        if force_move:
            return UnitMicroType.NONE
        nearest_priority, _ = self.enemy.get_closest_target(unit, included_types=[UnitTypeId.CYCLONE, UnitTypeId.SIEGETANKSIEGED, UnitTypeId.SIEGETANK, UnitTypeId.LURKERMP, UnitTypeId.LURKERMPBURROWED])
        if nearest_priority:
            if can_attack:
                return self._kite(unit, Units([nearest_priority], bot_object=self.bot))
            else:
                return self._stay_at_max_range(unit, Units([nearest_priority], bot_object=self.bot))
        return UnitMicroType.NONE

    @timed
    def _harass_attack_something(self, unit, health_threshold, harass_location: Point2, force_move: bool = False) -> UnitMicroType:
        # if unit.health_percentage <= self.harass_retreat_health:
        #     return UnitMicroType.NONE
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if force_move and not can_attack:
            return UnitMicroType.NONE
        nearby_enemy: Units
        attack_range_buffer = 0 if can_attack or unit.health_percentage <= self.harass_retreat_health else 5
        anti_banshee_structures = self.bot.enemy_structures.filter(
            lambda s: s.type_id in (UnitTypeId.MISSILETURRET, UnitTypeId.SPORECRAWLER, UnitTypeId.PHOTONCANNON))
        incomplete_structures = self.bot.enemy_structures.filter(
            lambda s: not s.is_ready
                        and s.is_visible
                        and (UnitTypes.can_attack_air(s) or s.health + s.shield < 50)
                        and (not anti_banshee_structures or anti_banshee_structures.closest_distance_to(s) > 6)
            ).sorted(lambda s: s.health + s.shield)
        nearby_enemy = self.enemy.in_attack_range(unit, incomplete_structures, 6, first_only=True)
        if not nearby_enemy:
            enemy_candidates = self.enemy.get_candidates(include_structures=False, include_out_of_view=False).sorted(lambda u: u.health + u.shield)
            nearby_enemy = self.enemy.in_attack_range(unit, enemy_candidates, attack_range_buffer, first_only=True)
            if not nearby_enemy and attack_range_buffer == 0:
                nearby_enemy = self.enemy.in_attack_range(unit, enemy_candidates, 5, first_only=True)
            if anti_banshee_structures:
                nearby_enemy = nearby_enemy.filter(lambda u: anti_banshee_structures.closest_distance_to(u) > 6)

        if UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies()):
            buffer = 3 if nearby_enemy and can_attack else 5
            threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=buffer)
            if threats:
                if nearby_enemy and can_attack:
                    threats_are_just_detectors = min([u.is_structure or u.type_id in UnitTypes.NON_THREAT_DETECTORS for u in threats])
                    if threats_are_just_detectors:
                        return self._kite(unit, nearby_enemy)
                if unit.health_percentage < self.harass_attack_health:
                    return UnitMicroType.NONE
                for threat in threats:
                    if threat.is_structure and self.distance_squared(unit, threat, self.enemy.predicted_position) > self.enemy.get_attack_range_with_buffer_squared(threat, unit, 3):
                        continue
                    if threat.is_flying or UnitTypes.air_range(threat) >= unit.ground_range:
                        # don't attack enemies that outrange
                        unit.move(self.get_circle_around_position(unit, threats.center, harass_location))
                        return UnitMicroType.MOVE

        if nearby_enemy:
            return self._kite(unit, nearby_enemy)
        if force_move or unit.health_percentage <= self.harass_retreat_health:
            return UnitMicroType.NONE
        # if can_attack:
        #     enemy_structures = self.bot.enemy_structures.sorted(lambda u: u.health + u.shield)
        #     nearby_enemy = self.enemy.in_attack_range(unit, enemy_structures, attack_range_buffer, first_only=True)
        #     if nearby_enemy:
        #         self._attack(unit, nearby_enemy.first)
        #         return UnitMicroType.ATTACK
        if unit.tag in self.harass_location_reached_tags:
            nearest_workers = self.enemy.get_closest_targets(unit, included_types=UnitTypes.WORKER_TYPES)
            if anti_banshee_structures:
                nearest_workers = nearest_workers.filter(lambda u: not self.unit_is_closer_than(u, anti_banshee_structures, 6))
            if nearest_workers:
                target = sorted(nearest_workers, key=lambda t: t.health + t.shield)[0]
                self._attack(unit, target)
                return UnitMicroType.ATTACK
        return UnitMicroType.NONE

    @timed_async
    async def _harass_retreat(self, unit: Unit, health_threshold: float, harass_location: Point2) -> UnitMicroType:
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE        

        do_retreat = unit.health_percentage <= self.harass_retreat_health

        can_be_attacked = UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies())
        if not can_be_attacked:
            if do_retreat:
                unit.move(self._get_retreat_destination(unit))
                return UnitMicroType.RETREAT
            return UnitMicroType.NONE
        
        threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=5)
        if not do_retreat:
            if not threats:
                if unit.health_percentage >= self.harass_attack_health:
                    return UnitMicroType.NONE
                do_retreat = True
            else:
                # retreat if there is nothing this unit can attack
                visible_threats = threats.filter(lambda t: t.age == 0 and t.is_visible)
                target = self.enemy.in_attack_range(unit, visible_threats, 3, first_only=True)
                if not target:
                    do_retreat = True

        # check if incoming damage will bring unit below health threshold
        if not do_retreat:
            total_potential_damage = sum([threat.calculate_damage_vs_target(unit)[0] for threat in threats])
            if not unit.health_max:
                # rare weirdness
                return UnitMicroType.RETREAT
            if (unit.health - total_potential_damage) / unit.health_max < self.harass_attack_health:
                do_retreat = True

        if do_retreat:
            retreat_position = self._get_retreat_destination(unit, threats)
            unit.move(retreat_position)
            return UnitMicroType.RETREAT
        return UnitMicroType.NONE