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
    cloak_energy_threshold: float = 25.0

    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if not self.cloak_researched:
            if UpgradeId.BANSHEECLOAK in self.bot.state.upgrades:
                self.cloak_researched = True
            else:
                return False
        if not unit.is_cloaked and unit.energy >= self.cloak_energy_threshold and self.enemy.threats_to(unit):
            unit(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)
        return False

    def _harass_attack_something(self, unit, health_threshold, force_move: bool = False):
        if unit.tag in BaseUnitMicro.repair_started_tags:
            if unit.health_percentage == 1.0 or self.bot.workers.closest_distance_to(unit) > 5:
                BaseUnitMicro.repair_started_tags.remove(unit.tag)
            else:
                return False
        if unit.health_percentage <= self.harass_retreat_health:
            return False
        if unit.health_percentage < self.harass_attack_health and self.can_be_attacked(unit):
            threats = self.enemy.threats_to(unit, attack_range_buffer=5)
            if threats:
                return False
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        nearby_enemies: Units
        if can_attack:
            nearby_enemies = self.enemy.get_enemies_in_range(unit, include_structures=False, include_destructables=False)
        else:
            nearby_enemies = self.enemy.threats_to(unit, attack_range_buffer=5)

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
        if self.can_be_attacked(unit):
            # enemy_workers = nearby_enemies.filter(lambda enemy: enemy.type_id in (UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE))
            threats = nearby_enemies.filter(lambda enemy: enemy.type_id not in (UnitTypeId.MULE, UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.LARVA, UnitTypeId.EGG))

            if threats:
                for threat in threats:
                    if UnitTypes.air_range(threat) >= unit.ground_range:
                        # don't attack enemies that outrange
                        return False
        weakest_enemy = nearby_enemies.sorted(key=lambda t: t.shield + t.health).first
        return self._kite(unit, weakest_enemy)
    
    def can_be_attacked(self, unit: Unit) -> bool:
        if unit.is_cloaked and unit.energy >= 5:
            observers = self.bot.enemy_units.of_type(UnitTypeId.OBSERVER)
            if observers and observers.closest_distance_to(unit) < 12:
                return True
            sieged_observers = self.bot.enemy_units.of_type(UnitTypeId.OBSERVERSIEGEMODE)
            if sieged_observers and sieged_observers.closest_distance_to(unit) < 16:
                return True
            photon_cannons = self.bot.enemy_structures.of_type(UnitTypeId.PHOTONCANNON)
            if photon_cannons and photon_cannons.closest_distance_to(unit) < 12:
                return True
            return False
        return True

    async def _harass_retreat(self, unit: Unit, health_threshold: float) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False        

        do_retreat = False

        if unit.health_percentage <= self.harass_retreat_health:
            if not self.can_be_attacked(unit):
                unit.move(self._get_retreat_destination(unit, Units([], self.bot)))
                return True
            do_retreat = True
        elif not self.can_be_attacked(unit):
            return False
        
        threats = self.enemy.threats_to(unit, attack_range_buffer=5)
        if not do_retreat:
            if not threats:
                if unit.health_percentage >= self.harass_attack_health:
                    return False
                do_retreat = True
            else:
                # retreat if there is nothing this unit can attack
                visible_threats = threats.filter(lambda t: t.age == 0)
                targets = UnitTypes.in_attack_range_of(unit, visible_threats, bonus_distance=3)
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
