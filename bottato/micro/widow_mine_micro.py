from __future__ import annotations
from typing import Dict
from loguru import logger

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.enums import UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, timed
from bottato.unit_types import UnitTypes
from bottato.unit_reference_helper import UnitReferenceHelper


class WidowMineMicro(BaseUnitMicro, GeometryMixin):
    max_burrow_time: float = 2.5
    time_in_frames_to_transform: float = max_burrow_time * 22.4
    attack_health: float = 0.4
    attack_range: float = 5.0
    burrowed_tags: set[int] = set()
    unburrowed_tags: set[int] = set()
    known_tags: set[int] = set()
    last_transform_time: Dict[int, float] = {}
    last_force_move_time: Dict[int, float] = {}
    drilling_claws_researched: bool = False
    current_targets: Dict[int, Unit | None] = {}
    last_lockon_time: Dict[int, float | None] = {}
    last_fire_time: Dict[int, float] = {}
    special_position: Dict[int, Point2] = {}
    last_special_position_update_time: float = 0.0

    @timed
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> UnitMicroType:
        if unit.tag not in self.known_tags:
            self.known_tags.add(unit.tag)
            self.unburrowed_tags.add(unit.tag)
        if unit.is_transforming:
            return UnitMicroType.NONE
        if not self.drilling_claws_researched:
            self.drilling_claws_researched = UpgradeId.DRILLCLAWS in self.bot.state.upgrades
            if self.drilling_claws_researched:
                self.max_burrow_time = 1.5
                self.time_in_frames_to_transform = self.max_burrow_time * 22.4

        if self.last_special_position_update_time != self.bot.time:
            self.last_special_position_update_time = self.bot.time
            self.special_position.clear()
            all_mines = self.bot.units.of_type({UnitTypeId.WIDOWMINE, UnitTypeId.WIDOWMINEBURROWED})
            latest_enemy_drop_locations = self.intel.get_recent_drop_locations(150)
            for mine in all_mines:
                if not latest_enemy_drop_locations:
                    break
                closest_drop_location = min(latest_enemy_drop_locations, key=lambda loc: mine.distance_to_squared(loc))
                self.special_position[mine.tag] = closest_drop_location
                latest_enemy_drop_locations.remove(closest_drop_location)

        is_burrowed = unit.type_id == UnitTypeId.WIDOWMINEBURROWED
        cooldown_remaining = max(0, 29 - (self.bot.time - self.last_fire_time.get(unit.tag, 0)))

        if unit.tag in self.special_position:
            special_pos = self.special_position[unit.tag]
            if not is_burrowed:
                if unit.position.distance_to(special_pos) > 2:
                    unit.move(special_pos)
                    return UnitMicroType.MOVE
                else:
                    self.burrow(unit)
                    return UnitMicroType.USE_ABILITY
            
            if unit.position.distance_to(special_pos) > 5:
                self.unburrow(unit)
                return UnitMicroType.USE_ABILITY
            return UnitMicroType.NONE

        if not is_burrowed:
            self.last_lockon_time[unit.tag] = None
            self.current_targets[unit.tag] = None
        else:
            last_lockon = self.last_lockon_time.get(unit.tag, None)
            if last_lockon:
                time_since_lockon = self.bot.time - last_lockon
                if time_since_lockon > 1.1:
                    self.last_fire_time[unit.tag] = self.bot.time - 0.4
                    self.last_lockon_time[unit.tag] = None
                    self.current_targets[unit.tag] = None
                    cooldown_remaining = 29 # just fired

            current_target = self.current_targets.get(unit.tag)
            if current_target:
                # check if previous target still in range
                try:
                    current_target = UnitReferenceHelper.get_updated_unit_reference(current_target)
                except UnitReferenceHelper.UnitNotFound:
                    self.last_lockon_time[unit.tag] = None
                    current_target = None
                if current_target:
                    if unit.distance_to_squared(current_target) > self.enemy.get_attack_range_with_buffer(unit, current_target, 0):
                        # lost target
                        self.last_lockon_time[unit.tag] = None
                        self.current_targets[unit.tag] = None
                        current_target = None

            if (not current_target or current_target.type_id == UnitTypeId.BROODLING) and cooldown_remaining == 0:
                # target new unit, if any in range
                targets_in_range = self.enemy.in_attack_range(unit, self.bot.enemy_units, -0.5)
                if targets_in_range:
                    new_target = max(targets_in_range, key=lambda t: t.health + t.shield - self.get_targeting_count(t) * 125)
                    unit.smart(new_target)
                    if new_target.health + new_target.shield > self.get_targeting_count(new_target) * 125:
                        # add to targetting count. without this it will keep restarting the attack cooldown
                        self.current_targets[unit.tag] = new_target
                        self.last_lockon_time[unit.tag] = self.bot.time

        last_transform = self.last_transform_time.get(unit.tag, -999)
        time_since_last_transform = self.bot.time - last_transform
        if is_burrowed != (unit.tag in self.burrowed_tags):
            # fix miscategorizations, though it's probably just transforming
            if time_since_last_transform > 1.5:
                if is_burrowed:
                    self.burrow(unit, update_last_transform_time=False)
                else:
                    self.unburrow(unit, update_last_transform_time=False)
            return UnitMicroType.USE_ABILITY

        if self.bot.time < 300:
            if not self.drilling_claws_researched and cooldown_remaining > 3:
                if is_burrowed:
                    self.unburrow(unit)
                    return UnitMicroType.USE_ABILITY
                return UnitMicroType.NONE
            if not is_burrowed:
                bunkers = self.bot.structures(UnitTypeId.BUNKER)
                burrow_position: Point2 | None = None
                if bunkers:
                    bunker = bunkers.furthest_to(self.bot.start_location)
                    burrow_position = bunker.position.towards(self.bot.start_location, bunker.radius)
                elif self.bot.structures.of_type(UnitTypeId.BARRACKS):
                    ramp_barracks = self.bot.structures.of_type(UnitTypeId.BARRACKS).closest_to(self.bot.main_base_ramp.barracks_correct_placement) # type: ignore
                    candidates = [(depot_position + ramp_barracks.position) / 2 for depot_position in self.bot.main_base_ramp.corner_depots]
                    candidate = min(candidates, key=lambda p: ramp_barracks.add_on_position.distance_to(p))
                    burrow_position = candidate.towards(self.bot.main_base_ramp.top_center.towards(ramp_barracks.position, distance=2), distance=-1)
                if burrow_position:
                    if unit.position.distance_to(burrow_position) < 1:
                        self.burrow(unit)
                        return UnitMicroType.USE_ABILITY
                    else:
                        unit.move(burrow_position)
                        return UnitMicroType.MOVE
            return UnitMicroType.NONE
                    
        excluded_enemy_types = [UnitTypeId.LARVA, UnitTypeId.EGG] if is_burrowed else UnitTypes.NON_THREATS
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
            if not self.drilling_claws_researched and 28.0 > cooldown_remaining > 3:
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
            if closest_distance <= self.attack_range + 4 and cooldown_remaining < 5:
                # burrow to attack
                self.burrow(unit)
                return UnitMicroType.USE_ABILITY
            elif do_force_move:
                return UnitMicroType.NONE
            elif closest_distance <= self.attack_range + 6 and cooldown_remaining < 2 and new_target:
                unit.move(new_target)
                return UnitMicroType.MOVE
            sieged_tanks = self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED)
            # or burrow near a sieged tank
            if new_target and sieged_tanks:
                closest_tank_to_enemy = self.closest_unit_to_unit(new_target, sieged_tanks)
                if closest_tank_to_enemy:
                    burrow_position = closest_tank_to_enemy.position.towards(new_target.position, closest_tank_to_enemy.radius + 1)
                    if unit.distance_to_squared(burrow_position) > 4:
                        unit.move(burrow_position)
                        return UnitMicroType.MOVE
                    else:
                        self.burrow(unit)
                        return UnitMicroType.USE_ABILITY
        return UnitMicroType.NONE
    
    def get_targeting_count(self, enemy_unit: Unit) -> int:
        return sum(1 for target in self.current_targets.values() if target and target.tag == enemy_unit.tag)

    def burrow(self, unit: Unit, update_last_transform_time: bool = True):
        unit(AbilityId.BURROWDOWN_WIDOWMINE)
        self.update_burrow_state(unit, self.unburrowed_tags, self.burrowed_tags, update_last_transform_time)

    def unburrow(self, unit: Unit, update_last_transform_time: bool = True):
        unit(AbilityId.BURROWUP_WIDOWMINE)
        self.update_burrow_state(unit, self.burrowed_tags, self.unburrowed_tags, update_last_transform_time)

    def update_burrow_state(self, unit: Unit, old_list: set, new_list: set, update_last_transform_time: bool = True):
        if update_last_transform_time:
            self.last_transform_time[unit.tag] = self.bot.time
        # new_list = self.bot.units.tags.intersection(new_list)
        if unit.tag not in new_list:
            new_list.add(unit.tag)
        else:
            logger.debug(f"{unit.tag} already in unburrowed_tags")
        if unit.tag in old_list:
            old_list.remove(unit.tag)
        else:
            logger.debug(f"{unit.tag} not in burrowed_tags")

    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> UnitMicroType:
        # just use auto attack
        return UnitMicroType.ATTACK if unit.tag in self.burrowed_tags else UnitMicroType.NONE
