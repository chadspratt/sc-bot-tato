from __future__ import annotations

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin
from bottato.unit_types import UnitTypes


class BansheeMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.58
    harass_attack_health: float = 0.9
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

    excluded_enemy_types = [
        UnitTypeId.LARVA,
        UnitTypeId.EGG
    ]
    target_structure_types = [
        UnitTypeId.SPINECRAWLER,
    ]

    def _harass_attack_something(self, unit, health_threshold, force_move: bool = False):
        if unit.health_percentage < self.harass_attack_health:
            threats = self.enemy.threats_to(unit, attack_range_buffer=5)
            if threats:
                return False
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if not can_attack:
            return False

        nearby_enemies = self.enemy.get_enemies_in_range(unit, include_structures=False, include_destructables=False)
        if not nearby_enemies:
            nearest_probe, _ = self.enemy.get_closest_target(unit, included_types=[UnitTypeId.PROBE])
            if nearest_probe:
                return self._kite(unit, nearest_probe)
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
        if unit.is_cloaked:
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
        if not self.can_be_attacked(unit):
            return False
        threats = self.enemy.threats_to(unit, attack_range_buffer=5)

        if not threats:
            if unit.health_percentage >= self.harass_attack_health:
                return False
            # just stop and wait for regen
            unit.stop()
            return True

        # retreat if there is nothing this unit can attack
        do_retreat = False
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
            avg_threat_position = threats.center
            if unit.distance_to(self.bot.start_location) < avg_threat_position.distance_to(self.bot.start_location) - 2:
                # if closer to start or already near enemy, move past them to go home
                unit.move(self.bot.start_location)
                return True
            retreat_position = unit.position.towards(avg_threat_position, -5)
            # .towards(self.bot.start_location, 2)
            if self.bot.in_map_bounds(retreat_position): # type: ignore
                unit.move(retreat_position) # type: ignore
            else:
                if unit.position == avg_threat_position:
                    # avoid divide by zero
                    unit.move(self.bot.start_location)
                else:
                    circle_around_position = self.get_circle_around_position(unit, avg_threat_position, self.bot.start_location)
                    unit.move(circle_around_position.towards(self.bot.start_location, 2)) # type: ignore
            return True
        return False
    
    # def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
    #     relevant_enemies = self.bot.enemy_units.filter(lambda u: u.armor < 10) + self.bot.enemy_structures.of_type(self.offensive_structure_types)
    #     nearby_enemies = relevant_enemies.closer_than(15, unit)
    #     nearby_structures = self.bot.enemy_structures.closer_than(15, unit)
    #     targets = nearby_enemies.filter(lambda u: not u.is_flying and u.type_id not in self.excluded_enemy_types)
    #     tanks: Units = targets.filter(lambda u: u.type_id in (UnitTypeId.SIEGETANKSIEGED, UnitTypeId.SIEGETANK))
    #     if not targets:
    #         targets = nearby_structures
    #     threats = nearby_enemies.filter(lambda u: UnitTypes.can_attack_air(u))
    #     can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
    #     if targets:
    #         if not threats:
    #             if tanks:
    #                 unit.attack(tanks.closest_to(unit))
    #             else:
    #                 unit.attack(targets.closest_to(unit))
    #             return True
    #         elif can_attack:
    #             max_threats = 0 if unit.health_percentage < health_threshold else 4
    #             attackable_threats = threats.filter(lambda u: not u.is_flying) + tanks
    #             closest_target = attackable_threats.closest_to(unit)
    #             if closest_target:
    #                 if len(threats) < max_threats or closest_target.distance_to(unit) < unit.ground_range - 0.5:
    #                     unit.attack(closest_target)
    #                     return True
    #             else:
    #                 closest_target = targets.closest_to(unit)
    #                 if len(threats) < max_threats or closest_target.distance_to(unit) < unit.ground_range - 0.5:
    #                     unit.attack(closest_target)
    #                     return True
    #         if self._retreat_to_tank(unit, can_attack):
    #             return True
    #         if self._stay_at_max_range(unit, threats):
    #             return True
    #     return False
