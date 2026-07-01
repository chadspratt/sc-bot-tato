from __future__ import annotations

from loguru import logger
from typing import Dict, List, Tuple

from cython_extensions.geometry import (
    cy_distance_to,
    cy_distance_to_squared,
    cy_towards,
)
from cython_extensions.units_utils import cy_center
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.protocol import ProtocolError
from sc2.unit import Unit
from sc2.units import Units

from bottato.enums import UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.unit_types import UnitTypes


class ReaperMicro(BaseUnitMicro, GeometryMixin):
    grenade_cooldown = 14.0
    grenade_timer = 1.7
    attack_health = 0.8
    retreat_health = 0.65
    time_in_frames_to_attack = 0.18 * 22.4

    grenade_cooldowns: dict[int, float] = {}
    unconfirmed_grenade_throwers: List[int] = []
    retreat_scout_location: Point2 | None = None
    bad_harass_experience_locations: Dict[Point2, Tuple[int, float]] = {}
    previous_elevation: dict[int, float] = {}
    last_hop_down_time: dict[int, float] = {}

    excluded_types = [UnitTypeId.EGG, UnitTypeId.LARVA]
    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, force_move: bool = False) -> UnitMicroType:
        # do this here so it gets done reliably
        current_elevation = self.bot.get_terrain_z_height(unit)
        if unit.tag not in self.previous_elevation:
            self.previous_elevation[unit.tag] = current_elevation
        last_elevation = self.previous_elevation[unit.tag]
        if current_elevation - last_elevation < -1:
            self.last_hop_down_time[unit.tag] = self.bot.time
            self.previous_elevation[unit.tag] = current_elevation
        elif current_elevation - last_elevation > 1:
            self.previous_elevation[unit.tag] = current_elevation

        if unit.health_percentage < self.retreat_health:
            return UnitMicroType.NONE
        targets: Units = self.tactics.enemy.get_enemies_in_range(unit, include_structures=False, excluded_types=self.excluded_types, visible_only=True)
        grenade_targets: List[Point2] = []
        if targets and await self.grenade_available(unit):
            for target_unit in targets:
                grenade_targets.append(target_unit.position)

        if grenade_targets:
            # choose furthest to reduce chance of grenading self
            grenade_target = min(grenade_targets, key=lambda p: cy_distance_to_squared(unit.position, p))
            logger.debug(f"{unit} grenading {grenade_target}")
            self.throw_grenade(unit, grenade_target)
            return UnitMicroType.USE_ABILITY

        return UnitMicroType.NONE

    @timed_async
    async def _harass_attack_something(self, unit, health_threshold, harass_location: Point2, force_move: bool = False) -> UnitMicroType:
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.ATTACK
        # below retreat_health: do nothing
        if unit.health_percentage < self.retreat_health:
            return UnitMicroType.NONE
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack

        is_low_health = unit.health_percentage < self.attack_health
        if is_low_health and not can_attack:
            return UnitMicroType.NONE
        # nearby_enemies: Units
        if self.bot.time - self.last_hop_down_time.get(unit.tag, 0) < 1:
            # recently hopped down while retreating, don't immediately go back up
            return UnitMicroType.NONE

        candidates = self.tactics.enemy.get_candidates(included_types={UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.ZERGLING, UnitTypeId.ZEALOT, UnitTypeId.MARINE, UnitTypeId.REAPER})
        if candidates:
            action = await self._kite(unit, candidates, force_move=force_move)
            if action == UnitMicroType.RETREAT:
                self.add_bad_harass_experience_location(unit, harass_location)
            return action
        return UnitMicroType.NONE
    
    def add_bad_harass_experience_location(self, unit: Unit, location: Point2):
        if cy_distance_to_squared(unit.position, location) <= 225:
            # must be at spot to give bad review
            try:
                curval = self.bad_harass_experience_locations[location]
                experience_count, last_time = curval
                if self.bot.time - last_time > 15:
                    self.bad_harass_experience_locations[location] = (experience_count + 1, self.bot.time)
            except KeyError:
                self.bad_harass_experience_locations[location] = (0, 0.0)

    # def _harass_move_unit(self, unit: Unit, target: Point2, previous_position: Point2 | None = None) -> UnitMicroType:
    #     if target not in self.bad_harass_experience_locations:
    #         self.bad_harass_experience_locations[target] = (0, 0.0)
    #     curval = self.bad_harass_experience_locations[target]
    #     target_exp_count, target_exp_time = curval
    #     preferred_target = target
    #     if target_exp_count > 0:
    #         for loc in list(self.bad_harass_experience_locations.keys()):
    #             exp_count, exp_time = self.bad_harass_experience_locations[loc]
    #             # go somewhere with fewer and less recent bad experiences
    #             if exp_count < target_exp_count and exp_time < target_exp_time:
    #                 preferred_target = loc
    #                 target_exp_count = exp_count
    #                 target_exp_time = exp_time
    #     position_to_compare = preferred_target if unit.is_moving else unit.position
    #     if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
    #         unit.move(self.tactics.map.get_pathable_position(target, unit))
    #         return UnitMicroType.MOVE
    #     return UnitMicroType.NONE

    @timed_async
    async def _harass_retreat(self, unit: Unit, health_threshold: float, harass_location: Point2) -> UnitMicroType:
        # below retreat_health: always retreat
        # below attack_health: retreat if threats
        # above attack_health: do nothing
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE

        recently_hopped = self.bot.time - self.last_hop_down_time.get(unit.tag, 0) < 1
        
        # above attack_health: do nothing
        if not recently_hopped and unit.health_percentage >= self.attack_health:
            self.retreat_scout_location = None
            return UnitMicroType.NONE

        threats = self.tactics.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6)

        # recently hopped down a cliff - move away from the edge before doing
        # anything else so the reaper doesn't immediately hop back up
        if recently_hopped and threats:
            away_position = Point2(cy_towards(unit.position, Point2(cy_center(threats)), -5))
            unit.move(self.tactics.map.get_pathable_position(away_position, unit))
            return UnitMicroType.RETREAT

        is_below_retreat_health = unit.health_percentage < health_threshold
        # check if incoming damage would bring unit below retreat_health
        if not is_below_retreat_health and threats:
            if not unit.health_max:
                return UnitMicroType.NONE
            hp_threshold = unit.health_max * health_threshold
            current_health = unit.health
            for threat in threats:
                if UnitTypes.ground_range(threat) > unit.ground_range:
                    # outranged, treat as below retreat
                    is_below_retreat_health = True
                    break
                current_health -= threat.calculate_damage_vs_target(unit)[0]
                if current_health < hp_threshold:
                    is_below_retreat_health = True
                    break

        # below retreat_health: always retreat
        if is_below_retreat_health:
            if not threats:
                # scout next enemy expansion location
                if self.retreat_scout_location is None or self.bot.is_visible(self.retreat_scout_location):
                    scout_locations = self.tactics.intel.get_next_enemy_expansion_scout_locations()
                    # pick a location that isn't visible
                    self.retreat_scout_location = min(scout_locations, key=lambda loc: self.bot.is_visible(loc.expansion_position)).expansion_position
                path = self.tactics.map.get_path(unit.position, self.retreat_scout_location)
                if path.zones:
                    # follow path to avoid hopping back up a cliff
                    unit.move(path.zones[1].midpoint)
                else:
                    # in the destination zone, just move to the location
                    unit.move(self.retreat_scout_location)
                return UnitMicroType.RETREAT

            destination = self.bot.start_location
            avg_threat_position = Point2(cy_center(threats))
            distance_to_start = cy_distance_to(unit.position, destination)
            if 30 < distance_to_start < cy_distance_to(avg_threat_position, destination) + 2:
                # if closer to start or already near enemy, move past them to go home
                unit.move(destination)
                return UnitMicroType.RETREAT
            # if retreat_to_start:
            _, retreat_position = await self._get_retreat_destination(unit, threats)
            unit.move(retreat_position)
            return UnitMicroType.RETREAT

        self.retreat_scout_location = None
        return UnitMicroType.NONE

    def throw_grenade(self, unit: Unit, target: Point2):
        unit(AbilityId.KD8CHARGE_KD8CHARGE, target)
        self.unconfirmed_grenade_throwers.append(unit.tag)

    async def grenade_available(self, unit: Unit) -> bool:
        if unit.tag in self.unconfirmed_grenade_throwers:
            try:
                available = await self.bot.can_cast(unit, AbilityId.KD8CHARGE_KD8CHARGE, only_check_energy_and_cooldown=True)
            except ProtocolError:
                # game ended
                return False
            self.unconfirmed_grenade_throwers.remove(unit.tag)
            if not available:
                self.grenade_cooldowns[unit.tag] = self.bot.time + self.grenade_cooldown
            else:
                return True
        elif unit.tag not in self.grenade_cooldowns:
            return True
        elif self.grenade_cooldowns[unit.tag] < self.bot.time:
            del self.grenade_cooldowns[unit.tag]
            return True
        return False
