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

        targets: Units = self.enemy.get_enemies_in_range(unit, include_structures=False, excluded_types=self.excluded_types)
        grenade_targets: List[Point2] = []
        if targets and await self.grenade_available(unit):
            for target_unit in targets:
                # if target_unit.is_flying or target_unit.age > 0:
                #     continue
                # future_target_position = self.enemy.get_predicted_position(target_unit, self.grenade_timer)
                # future_target_distance = cy_distance_to(future_target_position, unit.position)
                # if future_target_distance > 5:
                #     continue
                # grenade_target: Point2 = future_target_position
                # if cy_is_facing(target_unit, unit, angle_error=0.15):
                #     # throw towards current position to avoid cutting off own retreat when predicted position is behind
                #     grenade_target = Point2(cy_towards(unit.position, target_unit.position, future_target_distance))
                grenade_target: Point2 = target_unit.position
                grenade_targets.append(grenade_target)

        if grenade_targets:
            # choose furthest to reduce chance of grenading self
            grenade_target = min(grenade_targets, key=lambda p: cy_distance_to_squared(unit.position, p))
            logger.debug(f"{unit} grenading {grenade_target}")
            self.throw_grenade(unit, grenade_target)
            return UnitMicroType.USE_ABILITY

        return UnitMicroType.NONE

    @timed
    def _harass_attack_something(self, unit, health_threshold, harass_location: Point2, force_move: bool = False) -> UnitMicroType:
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
        candidates = self.enemy.get_candidates(included_types={UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE})
        worker_buffer = 0 if can_attack else 5
        nearby_workers = self.enemy.in_attack_range(unit, candidates, worker_buffer)
        if not nearby_workers and worker_buffer == 0:
            nearby_workers = self.enemy.in_attack_range(unit, candidates, 5)

        threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6)
        threats = threats.filter(lambda enemy: enemy.type_id not in UnitTypes.NON_THREATS)

        target = None
        targets: Units = Units([], bot_object=self.bot)
        if nearby_workers:
            # target lowest health but prioritize closest if very close
            target = nearby_workers.sorted(key=lambda t: t.shield + t.health).first
            closest_worker = self.closest_unit_to_unit(unit, nearby_workers)
            if self.enemy.safe_distance_squared(unit, closest_worker) < 9:
                targets.append(closest_worker)
                target = closest_worker

        if threats:
            closest_distance: float = float('inf')
            if target:
                closest_distance = self.enemy.safe_distance_squared(unit, target) - UnitTypes.ground_range(target)
            for threat in threats:
                if threat.age > 0 and is_low_health:
                    continue
                threat_range = UnitTypes.ground_range(threat)
                if threat_range > unit.ground_range or threat_range == unit.ground_range and unit.health < threat.health + threat.shield:
                    # don't attack enemies that outrange or have more health
                    self.add_bad_harass_experience_location(unit, harass_location)
                    return UnitMicroType.NONE
                threat_distance = self.distance(unit, threat, self.enemy.predicted_positions) - threat_range
                # if unit.health_percentage < self.attack_health and unit.health < threat.health + threat.shield - 10 and threat_distance < 2:
                #     self.add_bad_harass_experience_location(unit, harass_location)
                #     return UnitMicroType.NONE
                threat_distance_squared = self.enemy.safe_distance_squared(unit, threat)
                reaper_range_distance = self.enemy.get_attack_range_with_buffer_squared(unit, threat, 0)
                threat_is_in_range = threat_distance_squared <= reaper_range_distance
                threat_range_distance = self.enemy.get_attack_range_with_buffer_squared(threat, unit, 1)
                reaper_is_threatened = threat_distance_squared <= threat_range_distance
                if threat_distance < closest_distance:
                    closest_distance = threat_distance
                    target = threat
                if threat_is_in_range or reaper_is_threatened:
                    if threat.age > 0:
                        height_difference = threat.position3d.z - self.bot.get_terrain_z_height(unit)
                        if height_difference > 0.5:
                            # don't attack enemies significantly higher than us
                            self.add_bad_harass_experience_location(unit, harass_location)
                            return UnitMicroType.NONE
                    targets.append(threat)

        if not targets:
            if unit.tag in self.harass_location_reached_tags and not is_low_health:
                nearest_workers = self.enemy.get_closest_targets(unit, included_types=UnitTypes.WORKER_TYPES)
                if nearest_workers:
                    return self._kite(unit, nearest_workers)
            return UnitMicroType.NONE

        if self.bot.time - self.last_hop_down_time.get(unit.tag, 0) < 1:
            # recently hopped down while retreating, don't immediately go back up
            return UnitMicroType.NONE

        return self._kite(unit, targets)
    
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
    #         unit.move(self.map.get_pathable_position(target, unit))
    #         return UnitMicroType.MOVE
    #     return UnitMicroType.NONE

    @timed_async
    async def _harass_retreat(self, unit: Unit, health_threshold: float, harass_location: Point2) -> UnitMicroType:
        # below retreat_health: always retreat
        # below attack_health: retreat if threats
        # above attack_health: do nothing
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE

        # recently hopped down a cliff - move away from the edge before doing
        # anything else so the reaper doesn't immediately hop back up
        recently_hopped = self.bot.time - self.last_hop_down_time.get(unit.tag, 0) < 1
        if recently_hopped:
            threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6)
            if threats:
                away_position = Point2(cy_towards(unit.position, Point2(cy_center(threats)), -5))
            else:
                away_position = Point2(cy_towards(unit.position, harass_location, -5))
            unit.move(self.map.get_pathable_position(away_position, unit))
            return UnitMicroType.RETREAT

        # above attack_health: do nothing
        if unit.health_percentage >= self.attack_health:
            self.retreat_scout_location = None
            return UnitMicroType.NONE

        threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6)

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
                    scout_locations = self.intel.get_next_enemy_expansion_scout_locations()
                    # pick a location that isn't visible
                    self.retreat_scout_location = min(scout_locations, key=lambda loc: self.bot.is_visible(loc.expansion_position)).expansion_position
                path = self.map.get_path(unit.position, self.retreat_scout_location)
                if path.zones:
                    # follow path to avoid hopping back up a cliff
                    unit.move(path.zones[1].midpoint)
                else:
                    # might be on a double ledge with no pathing
                    unit.move(self.bot.start_location)
                return UnitMicroType.RETREAT

            destination = self.bot.start_location
            avg_threat_position = Point2(cy_center(threats))
            if cy_distance_to(unit.position, destination) < cy_distance_to(avg_threat_position, destination) + 2:
                # if closer to start or already near enemy, move past them to go home
                unit.move(destination)
                return UnitMicroType.RETREAT
            # if retreat_to_start:
            retreat_position = self._get_retreat_destination(unit, threats)
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
