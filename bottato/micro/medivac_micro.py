from __future__ import annotations

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bottato.unit_types import UnitTypes
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin


class MedivacMicro(BaseUnitMicro, GeometryMixin):
    heal_cost = 1
    heal_start_cost = 5
    heal_range = 4
    heal_range_sq = 16
    ability_health = 0.5
    pick_up_range = 2
    health_threshold_for_healing = 0.75

    stopped_for_healing: set[int] = set()
    injured_bio: Units
    injured_bio_last_update: int = -1
    last_afterburner_time: dict[int, float] = {}
    units_to_pick_up: Units
    units_to_pick_up_last_update: int = -1
    units_to_pick_up_potential_damage: dict[int, float] = {}
    threat_damage: dict[UnitTypeId, float] = {}

    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        threats = self.enemy.threats_to_friendly_unit(unit, 4)
        if unit.health_percentage < self.health_threshold_for_healing:
            if threats:
                if unit.tag not in self.last_afterburner_time or self.bot.time - self.last_afterburner_time[unit.tag] > 14.0:
                    unit(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)
                    self.last_afterburner_time[unit.tag] = self.bot.time
                elif unit.cargo_used > 0 and unit.health_percentage < 0.3:
                    unit(AbilityId.UNLOADALLAT, unit)
                return False
            elif force_move:
                return False
        target_distance_to_start = target._distance_squared(self.bot.start_location)
        enemy_distance_to_target = self.closest_distance_squared(target, self.bot.enemy_units) if self.bot.enemy_units else 999999
        # only ferry units on retreat
        if force_move and self.bot.time > 300 and unit.cargo_left > 0 and enemy_distance_to_target > 400:
            if self.units_to_pick_up_last_update != self.bot._total_steps_iterations:
                self.units_to_pick_up_last_update = self.bot._total_steps_iterations
                self.units_to_pick_up = Units([], self.bot)
                for u in self.bot.units:
                    if u.type_id == UnitTypeId.SIEGETANKSIEGED or u.is_flying or u.movement_speed >= unit.movement_speed:
                        continue
                    u_distance_to_start = u.distance_to_squared(self.bot.start_location)
                    u_distance_to_target = u.distance_to_squared(target)
                    if 225 < u_distance_to_target < u_distance_to_start and target_distance_to_start < u_distance_to_start:
                        self.units_to_pick_up.append(u)
                self.units_to_pick_up_potential_damage.clear()
                # calculate potential damage to a medivac if it tried to pick up each unit
                if self.units_to_pick_up and self.bot.enemy_units:
                    threats = self.bot.enemy_units.filter(lambda e: UnitTypes.air_range(e) > 0)
                    for passenger in self.units_to_pick_up:
                        potential_damage = 0
                        for threat in threats:
                            if threat.type_id not in self.threat_damage:
                                self.threat_damage[threat.type_id] = threat.calculate_damage_vs_target(unit)[0]
                            if self.threat_damage[threat.type_id] <= 0:
                                continue
                            if threat.distance_to(passenger) + self.pick_up_range <= UnitTypes.air_range(threat):
                                potential_damage += self.threat_damage[threat.type_id]
                        self.units_to_pick_up_potential_damage[passenger.tag] = potential_damage
                # prioritize slower units, tiebreak with further from home
                self.units_to_pick_up.sort(key=lambda u: u.movement_speed * 10000 - u.distance_to_squared(self.bot.start_location))
            for passenger in self.units_to_pick_up:
                if passenger.distance_to_squared(target) < unit.distance_to_squared(target):
                    # skip units that are already closer to the target
                    continue
                if passenger.cargo_size <= unit.cargo_left and self.units_to_pick_up_potential_damage.get(passenger.tag, 0) < unit.health:
                    unit(AbilityId.LOAD, passenger)
                    passenger.move(unit.position) # possible passenger already received an order, but shouldn't hurt
                    self.units_to_pick_up.remove(passenger)
                    return True
        if unit.cargo_used > 0 and (unit.distance_to_squared(target) < 100 or enemy_distance_to_target <= 400):
            unit(AbilityId.UNLOADALLAT, unit)
            return True
        if not self.heal_available(unit):
            return False
        if force_move and threats:
            return False
        
        # refresh list of injured bio once per iteration
        if self.injured_bio_last_update != self.bot._total_steps_iterations:
            self.injured_bio_last_update = self.bot._total_steps_iterations
            self.injured_bio = self.bot.units.filter(lambda u: u.is_biological and u.health_percentage < 1.0)

        if self.injured_bio:
            nearest_injured = self.injured_bio.closest_to(unit)
            if nearest_injured.distance_to_squared(unit) < 400:
                if self.distance_squared(unit, nearest_injured) <= self.heal_range_sq:
                    # prioritize closest otherwise it defaults to lowest which delays units rejoining battle
                    unit(AbilityId.MEDIVACHEAL_HEAL, nearest_injured)
                    # unit.stop()
                    self.stopped_for_healing.add(unit.tag)
                else:
                    unit.move(nearest_injured)
                    if unit.tag in self.stopped_for_healing:
                        self.stopped_for_healing.remove(unit.tag)

        return unit.tag in self.bot.unit_tags_received_action

    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> bool:
        # doesn't have an attack
        if unit.health_percentage > self.health_threshold_for_healing:
            return self._retreat_to_tank(unit, can_attack=False)
        return False

    def heal_available(self, unit: Unit) -> bool:
        if unit.tag in self.stopped_for_healing:
            if unit.energy >= self.heal_cost:
                return True
            else:
                self.stopped_for_healing.remove(unit.tag)
                return False
        else:
            return unit.energy >= self.heal_start_cost
