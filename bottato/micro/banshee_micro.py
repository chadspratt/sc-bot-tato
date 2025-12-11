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
    attack_health: float = 0.58
    harass_attack_health: float = 0.9
    harass_retreat_health: float = 0.5
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
    
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        return self._harass_attack_something(unit, health_threshold, force_move)

    def _harass_attack_something(self, unit, health_threshold, force_move: bool = False):
        if unit.tag in BaseUnitMicro.repair_started_tags:
            if unit.health_percentage == 1.0 or self.bot.workers.closest_distance_to(unit) > 5:
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
            threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=1)
            if threats:
                for threat in threats:
                    if UnitTypes.air_range(threat) >= unit.ground_range:
                        # don't attack enemies that outrange
                        return False
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        nearby_enemies: Units
        attack_range_buffer = 0 if can_attack else 5
        enemy_candidates = self.enemy.get_candidates(include_structures=False, include_out_of_view=False)
        nearby_enemies = self.enemy.in_attack_range(unit, enemy_candidates, attack_range_buffer)

        if not nearby_enemies:
            if unit.tag in self.harass_location_reached_tags:
                nearest_probe, _ = self.enemy.get_closest_target(unit, included_types=[UnitTypeId.PROBE])
                if nearest_probe:
                    if can_attack:
                        return self._kite(unit, nearest_probe)
                    else:
                        unit.move(nearest_probe.position)
                        return True
            return False
        weakest_enemy = nearby_enemies.sorted(key=lambda t: t.shield + t.health).first
        return self._kite(unit, weakest_enemy)

    async def _harass_retreat(self, unit: Unit, health_threshold: float) -> bool:
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
                targets = self.enemy.in_attack_range(unit, visible_threats, 3)
                if not targets:
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
