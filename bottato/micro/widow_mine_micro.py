from __future__ import annotations

from loguru import logger
from typing import Dict, List

from cython_extensions.geometry import (
    cy_distance_to,
    cy_distance_to_squared,
    cy_towards,
)
from cython_extensions.units_utils import cy_closest_to
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.enums import UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, timed
from bottato.unit_reference_helper import UnitReferenceHelper
from bottato.unit_types import UnitTypes


class WidowMineMicro(BaseUnitMicro, GeometryMixin):
    max_burrow_time: float = 2.5
    time_in_frames_to_transform: float = max_burrow_time * 22.4
    attack_health: float = 0.5
    attack_range: float = 5.0
    burrowed_count: int = 0
    known_tags: set[int] = set()
    last_tag_refresh: float = 0
    last_transform_time: Dict[int, float] = {}
    last_force_move_time: Dict[int, float] = {}
    drilling_claws_researched: bool = False
    current_targets: Dict[int, Unit | None] = {}
    last_lockon_time: Dict[int, float | None] = {}
    last_fire_time: Dict[int, float] = {}
    special_positions: Dict[int, Point2] = {}
    last_special_position_update_time: float = 0.0
    health_on_burrow: Dict[int, float] = {}

    @timed
    async def _use_ability(self, unit: Unit, target: Point2, force_move: bool = False) -> UnitMicroType:
        if unit.is_transforming:
            return UnitMicroType.NONE
        # update drilling claws status
        if not self.drilling_claws_researched:
            self.drilling_claws_researched = UpgradeId.DRILLCLAWS in self.bot.state.upgrades
            if self.drilling_claws_researched:
                self.max_burrow_time = 1.5
                self.time_in_frames_to_transform = self.max_burrow_time * 22.4
        
        if self.bot.time != self.last_tag_refresh:
            self.last_tag_refresh = self.bot.time
            self.known_tags = self.bot.units.of_type({UnitTypeId.WIDOWMINE, UnitTypeId.WIDOWMINEBURROWED}).tags
            self.burrowed_count = self.bot.units.of_type({UnitTypeId.WIDOWMINEBURROWED}).amount

        is_burrowed = unit.type_id == UnitTypeId.WIDOWMINEBURROWED
        rearm_cooldown_remaining = max(0, 29 - (self.bot.time - self.last_fire_time.get(unit.tag, 0)))

        if unit.tag not in self.current_targets and unit.health_percentage < self.health_on_burrow.get(unit.tag, 1.0):
            # get out of there, they've made your position!
            if is_burrowed:
                self.unburrow(unit)
                return UnitMicroType.USE_ABILITY
            return UnitMicroType.NONE

        # calculate special positions to burrow to block enemy drops based on recent drop locations
        if self.last_special_position_update_time != self.bot.time:
            self.last_special_position_update_time = self.bot.time
            self.special_positions.clear()
            all_mines = self.bot.units.of_type({UnitTypeId.WIDOWMINE, UnitTypeId.WIDOWMINEBURROWED})
            latest_enemy_drop_locations = self.intel.get_recent_drop_locations(150)
            for mine in all_mines:
                if not latest_enemy_drop_locations:
                    break
                if self.current_targets.get(mine.tag, None):
                    # don't move mines that are already locked on
                    continue
                closest_drop_location = min(latest_enemy_drop_locations, key=lambda loc: cy_distance_to_squared(mine.position, loc))
                self.special_positions[mine.tag] = closest_drop_location
                latest_enemy_drop_locations.remove(closest_drop_location)

        # send mines to special positions to block drops
        if unit.tag in self.special_positions:
            special_pos = self.special_positions[unit.tag]
            if not is_burrowed:
                if cy_distance_to(unit.position, special_pos) > 2:
                    unit.move(special_pos)
                    return UnitMicroType.MOVE
                else:
                    self.burrow(unit)
                    return UnitMicroType.USE_ABILITY
            
            if cy_distance_to(unit.position, special_pos) > 5:
                self.unburrow(unit)
                return UnitMicroType.USE_ABILITY
            return UnitMicroType.NONE

        # track lockon status (no data in api for whether it is locked) and update targeting when needed
        if not is_burrowed:
            self.last_lockon_time[unit.tag] = None
            self.current_targets[unit.tag] = None
        else:
            # manually track cooldown to fire at current target. have to guess when it fires since no api data
            last_lockon = self.last_lockon_time.get(unit.tag, None)
            if last_lockon:
                time_since_lockon = self.bot.time - last_lockon
                if time_since_lockon > 1.1:
                    self.last_fire_time[unit.tag] = self.bot.time - 0.4
                    self.last_lockon_time[unit.tag] = None
                    self.current_targets[unit.tag] = None
                    rearm_cooldown_remaining = 29 # just fired

            # check if target still in range to maintain lock
            current_target = self.current_targets.get(unit.tag)
            if current_target:
                try:
                    current_target = UnitReferenceHelper.get_updated_unit_reference(current_target)
                except UnitReferenceHelper.UnitNotFound:
                    self.last_lockon_time[unit.tag] = None
                    current_target = None
                if current_target:
                    if unit.distance_to_squared(current_target) > self.enemy.get_attack_range_with_buffer_squared(unit, current_target, 0):
                        # lost target
                        self.last_lockon_time[unit.tag] = None
                        self.current_targets[unit.tag] = None
                        current_target = None

            if rearm_cooldown_remaining == 0:
                # check if current target needs to change due to overkill
                if current_target:
                    remaining_hp_on_current_target = current_target.health + current_target.shield - self.get_targeting_count(current_target) * 125
                    min_health_to_attack = 25
                    allowed_excess = 125 - min_health_to_attack
                    overkill_damage = -remaining_hp_on_current_target - allowed_excess
                    if overkill_damage < 0:
                        # not overkilling
                        return UnitMicroType.NONE
                    excess_mine_count: int = int((overkill_damage + 124) // 125)
                    if unit.tag not in self.get_recent_lockons(current_target, excess_mine_count):
                        # this mine is not overkilling
                        return UnitMicroType.NONE

                # find best target to attack within range, excluding targets that are already heavily targeted by other mines to avoid overkill
                valid_targets = self.bot.enemy_units.filter(lambda e: e.type_id not in [UnitTypeId.BROODLING, UnitTypeId.LARVA, UnitTypeId.EGG,
                                                                                        UnitTypeId.ADEPTPHASESHIFT, UnitTypeId.CHANGELING]
                                                                                        and e.health + e.shield > self.get_targeting_count(e) * 125)
                targets_in_range = self.enemy.in_attack_range(unit, valid_targets, -0.1)
                if targets_in_range:
                    new_target = max(targets_in_range, key=lambda t: t.health + t.shield - self.get_targeting_count(t) * 125)
                    unit.smart(new_target)
                    self.current_targets[unit.tag] = new_target
                    self.last_lockon_time[unit.tag] = self.bot.time
                elif current_target:
                    # not sure if this successfully resets the cd to fire, still seem to get overkill
                    unit.smart(current_target)


        # early game placement, defend top of ramp
        if self.bot.time < 300:
            # stay unburrowed while revealed
            if not self.drilling_claws_researched and rearm_cooldown_remaining > 3:
                if is_burrowed:
                    self.unburrow(unit)
                    return UnitMicroType.USE_ABILITY
                return UnitMicroType.NONE
            
            if not is_burrowed:
                burrow_position: Point2 | None = None
                # burrow behind ramp barracks
                if self.bot.structures.of_type(UnitTypeId.BARRACKS):
                    ramp_barracks = cy_closest_to(self.bot.main_base_ramp.barracks_correct_placement, self.bot.structures.of_type(UnitTypeId.BARRACKS)) # type: ignore
                    burrow_position = Point2(cy_towards(ramp_barracks.position,
                                                        self.bot.main_base_ramp.top_center,
                                                        distance=-1.5))
                else:
                    burrow_position = self.bot.main_base_ramp.top_center

                if cy_distance_to(unit.position, burrow_position) < 1:
                    self.burrow(unit)
                    return UnitMicroType.USE_ABILITY
                else:
                    unit.move(burrow_position)
                    return UnitMicroType.MOVE
            return UnitMicroType.NONE
                    
        excluded_enemy_types = {UnitTypeId.LARVA, UnitTypeId.EGG, UnitTypeId.ADEPTPHASESHIFT} if is_burrowed else UnitTypes.NON_THREATS
        new_target, closest_distance = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False,
                                                                        excluded_types=excluded_enemy_types)

        if closest_distance > 25:
            new_target = None
        if force_move:
            self.last_force_move_time[unit.tag] = self.bot.time
        do_force_move = unit.tag in self.last_force_move_time and ((self.bot.time - self.last_force_move_time[unit.tag]) < 0.5)
            
        if is_burrowed:
            if do_force_move and closest_distance > self.attack_range + 4:
                self.unburrow(unit)
                return UnitMicroType.USE_ABILITY
            # unburrow if exposed
            if not self.drilling_claws_researched and 28.0 > rearm_cooldown_remaining > 3:
                self.unburrow(unit)
                return UnitMicroType.USE_ABILITY
            # stay burrowed if within 6 of attacking range
            if closest_distance <= self.attack_range + 6:
                return UnitMicroType.NONE  # keep burrowed to attack/hide
            else:
                sieged_tanks = self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED)
                closest_tank_to_enemy = self.closest_unit_to_unit(new_target, sieged_tanks) if new_target and sieged_tanks else None
                if closest_tank_to_enemy is None or closest_tank_to_enemy.distance_to_squared(unit) > 36:
                    # reposition to guard tank closest to enemy or to find enemies
                    self.unburrow(unit)
                    return UnitMicroType.USE_ABILITY
            return UnitMicroType.NONE
        else:
            # burrow if within 4 of attacking range
            if closest_distance <= self.attack_range + 4 and rearm_cooldown_remaining < 5:
                # burrow to attack
                self.burrow(unit)
                return UnitMicroType.USE_ABILITY
            elif do_force_move:
                return UnitMicroType.NONE
            elif closest_distance <= self.attack_range + 6 and rearm_cooldown_remaining < 2 and new_target:
                unit.move(new_target)
                return UnitMicroType.MOVE
            sieged_tanks = self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED)
            # or burrow near a sieged tank
            if new_target and sieged_tanks:
                closest_tank_to_enemy = self.closest_unit_to_unit(new_target, sieged_tanks)
                if closest_tank_to_enemy:
                    burrow_position = Point2(cy_towards(closest_tank_to_enemy.position, new_target.position, closest_tank_to_enemy.radius + 1))
                    if cy_distance_to_squared(unit.position, burrow_position) > 4:
                        unit.move(burrow_position)
                        return UnitMicroType.MOVE
                    else:
                        self.burrow(unit)
                        return UnitMicroType.USE_ABILITY
        return UnitMicroType.NONE
    
    def get_targeting_count(self, enemy_unit: Unit) -> int:
        return sum(1 for target in self.current_targets.values() if target and target.tag == enemy_unit.tag)
    
    def get_recent_lockons(self, enemy_unit: Unit, count: int) -> List[int]:
        mines_targeting_enemy = []
        for mine_tag, target in self.current_targets.items():
            if target and target.tag == enemy_unit.tag and self.last_lockon_time[mine_tag]:
                mines_targeting_enemy.append(mine_tag)
        sorted_mine_tags = sorted(mines_targeting_enemy, key=lambda t: self.last_lockon_time[t], reverse=True) # type: ignore
        return sorted_mine_tags[:count]

    def burrow(self, unit: Unit, update_last_transform_time: bool = True):
        unit(AbilityId.BURROWDOWN_WIDOWMINE)
        self.health_on_burrow[unit.tag] = unit.health_percentage
        self.update_burrow_state(unit, update_last_transform_time)

    def unburrow(self, unit: Unit, update_last_transform_time: bool = True):
        unit(AbilityId.BURROWUP_WIDOWMINE)
        self.update_burrow_state(unit, update_last_transform_time)

    def update_burrow_state(self, unit: Unit, update_last_transform_time: bool = True):
        if update_last_transform_time:
            self.last_transform_time[unit.tag] = self.bot.time

    def _attack_something(self, unit: Unit, health_threshold: float, move_position: Point2, force_move: bool = False) -> UnitMicroType:
        return UnitMicroType.ATTACK if unit.type_id == UnitTypeId.WIDOWMINEBURROWED else UnitMicroType.NONE
