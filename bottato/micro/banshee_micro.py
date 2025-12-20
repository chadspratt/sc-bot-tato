from __future__ import annotations

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin
from bottato.unit_types import UnitTypes


class BansheeMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.65
    harass_attack_health: float = 0.8
    harass_retreat_health: float = 0.6
    retreat_health: float = 0.6
    cloak_researched: bool = False
    cloak_energy_threshold: float = 40.0

    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if not self.cloak_researched:
            if UpgradeId.BANSHEECLOAK in self.bot.state.upgrades:
                self.cloak_researched = True
            else:
                return False
        if not unit.is_cloaked:
            threats = self.enemy.get_enemies().filter(
                lambda u: not u.is_detector)
            if unit.energy >= self.cloak_energy_threshold and self.enemy.threats_to(unit, threats, 2):
                unit(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
        else:
            if unit.health_percentage < self.harass_attack_health and not self.unit_is_closer_than(unit, self.enemy.get_enemies(), 15, self.bot):
                unit(AbilityId.BEHAVIOR_CLOAKOFF_BANSHEE)
        return False
    
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> bool:
        if unit.tag in BaseUnitMicro.repair_started_tags:
            if unit.health_percentage == 1.0 or self.closest_distance(unit, self.bot.workers) > 5:
                BaseUnitMicro.repair_started_tags.remove(unit.tag)
            else:
                return False
        if unit.health_percentage <= self.retreat_health:
            return False
        if UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies()) \
                and unit.health_percentage < self.attack_health \
                and self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=3):
            return False
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if force_move and not can_attack:
            return False
        attack_range_buffer = 0 if can_attack else 5
        enemy_candidates = self.enemy.get_candidates(include_out_of_view=False).sorted(lambda u: u.health + u.shield)
        attack_target = self._get_attack_target(unit, enemy_candidates, attack_range_buffer)
        if attack_target:
            return self._kite(unit, attack_target)

        if force_move:
            return False
        nearest_priority, _ = self.enemy.get_closest_target(unit, included_types=[UnitTypeId.SIEGETANKSIEGED, UnitTypeId.SIEGETANK, UnitTypeId.LURKERMP, UnitTypeId.LURKERMPBURROWED])
        if nearest_priority:
            if can_attack:
                return self._kite(unit, nearest_priority)
            else:
                return self._stay_at_max_range(unit, Units([nearest_priority], bot_object=self.bot))
        return False

    def _harass_attack_something(self, unit, health_threshold, harass_location: Point2, force_move: bool = False):
        if unit.tag in BaseUnitMicro.repair_started_tags:
            if unit.health_percentage == 1.0 or self.closest_distance(unit, self.bot.workers) > 5:
                BaseUnitMicro.repair_started_tags.remove(unit.tag)
            else:
                return False
        if unit.health_percentage <= self.harass_retreat_health:
            return False
        if unit.health_percentage < self.harass_attack_health and UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies()):
            threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=5)
            if threats:
                return False
        if UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies()):
            threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=5)
            if threats:
                for threat in threats:
                    if threat.is_flying or UnitTypes.air_range(threat) >= unit.ground_range:
                        # don't attack enemies that outrange
                        unit.move(self.get_circle_around_position(unit, threats.center, harass_location))
                        return True
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if force_move and not can_attack:
            return False
        nearby_enemy: Units
        attack_range_buffer = 0 if can_attack else 5
        enemy_candidates = self.enemy.get_candidates(include_structures=False, include_out_of_view=False).sorted(lambda u: u.health + u.shield)
        nearby_enemy = self.enemy.in_attack_range(unit, enemy_candidates, attack_range_buffer, first_only=True)

        if nearby_enemy:
            return self._kite(unit, nearby_enemy.first)
        if force_move:
            return False
        if unit.tag in self.harass_location_reached_tags:
            nearest_worker, _ = self.enemy.get_closest_target(unit, included_types=[UnitTypeId.PROBE, UnitTypeId.SCV, UnitTypeId.DRONE])
            if nearest_worker:
                if can_attack:
                    return self._kite(unit, nearest_worker)
                else:
                    unit.move(nearest_worker.position)
                    return True
        return False

    async def _harass_retreat(self, unit: Unit, health_threshold: float, harass_location: Point2) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False        

        do_retreat = False

        if unit.health_percentage <= self.harass_retreat_health:
            if not UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies()):
                unit.move(self._get_retreat_destination(unit, Units([], self.bot)))
                return True
            do_retreat = True
        elif not UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies()):
            return False
        
        threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=5)
        if not do_retreat:
            if not threats:
                if unit.health_percentage >= self.harass_attack_health:
                    return False
                do_retreat = True
            else:
                # retreat if there is nothing this unit can attack
                visible_threats = threats.filter(lambda t: t.age == 0)
                target = self.enemy.in_attack_range(unit, visible_threats, 3, first_only=True)
                if not target:
                    do_retreat = True

        # check if incoming damage will bring unit below health threshold
        if not do_retreat:
            total_potential_damage = sum([threat.calculate_damage_vs_target(unit)[0] for threat in threats])
            if not unit.health_max:
                # rare weirdness
                return True
            if (unit.health - total_potential_damage) / unit.health_max < self.harass_attack_health:
                do_retreat = True

        if do_retreat:
            retreat_position = self._get_retreat_destination(unit, threats)
            unit.move(retreat_position)
            return True
        return False
