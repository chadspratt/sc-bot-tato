from __future__ import annotations
from typing import Dict
from loguru import logger

from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

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

    @timed
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if unit.tag not in self.known_tags:
            self.known_tags.add(unit.tag)
            self.unburrowed_tags.add(unit.tag)
        if unit.is_transforming:
            return False
        if not self.drilling_claws_researched:
            self.drilling_claws_researched = UpgradeId.DRILLCLAWS in self.bot.state.upgrades
            if self.drilling_claws_researched:
                self.max_burrow_time = 1.5
                self.time_in_frames_to_transform = self.max_burrow_time * 22.4

        is_burrowed = unit.type_id == UnitTypeId.WIDOWMINEBURROWED
        cooldown_remaining = max(0, 29 - (self.bot.time - self.last_fire_time.get(unit.tag, 0)))

        if not is_burrowed:
            self.last_lockon_time[unit.tag] = None
            self.current_targets[unit.tag] = None
        else:
            last_lockon = self.last_lockon_time.get(unit.tag, None)
            if last_lockon:
                time_since_lockon = self.bot.time - last_lockon
                if time_since_lockon > 1.08:
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
                    if unit.distance_to_squared(current_target) > self.enemy.get_attack_range_with_buffer(unit, current_target, 1):
                        # lost target
                        self.last_lockon_time[unit.tag] = None
                        current_target = None

            if not current_target and cooldown_remaining == 0:
                # target new unit, if any in range
                targets_in_range = self.enemy.in_attack_range(unit, self.bot.enemy_units)
                if targets_in_range:
                    new_target = max(targets_in_range, key=lambda t: t.health + t.shield)
                    self.current_targets[unit.tag] = new_target
                    unit.smart(new_target)
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
            return True

        if self.bot.time < 300:
            if is_burrowed:
                if not self.drilling_claws_researched and cooldown_remaining > 3:
                    self.unburrow(unit)
                    return True
                return False
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
                        return True
                    else:
                        unit.move(burrow_position)
                        return True
                    
        excluded_enemy_types = [UnitTypeId.LARVA, UnitTypeId.EGG] if is_burrowed else UnitTypes.NON_THREATS
        new_target, closest_distance = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False,
                                                                        excluded_types=excluded_enemy_types)

        if closest_distance > 25:
            new_target = None
        if force_move:
            self.last_force_move_time[unit.tag] = self.bot.time
        if unit.tag in self.last_force_move_time and ((self.bot.time - self.last_force_move_time[unit.tag]) < 0.5):
            if is_burrowed and closest_distance > self.attack_range + 1:
                # and friendly_buffer_count < 5:
                self.unburrow(unit)
                return True
            else:
                return False
            
        if is_burrowed:
            if not self.drilling_claws_researched and cooldown_remaining > 3:
                self.unburrow(unit)
                return True
            if closest_distance <= self.attack_range + 2:
                return False  # keep burrowed to attack/hide
            else:
                sieged_tanks = self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED)
                closest_tank_to_enemy = self.closest_unit_to_unit(new_target, sieged_tanks) if new_target and sieged_tanks else None
                if closest_tank_to_enemy is None or closest_tank_to_enemy.distance_to_squared(unit) > 36:
                    # reposition to guard tank closest to enemy
                    self.unburrow(unit)
                    return True
            return False
        else:
            if closest_distance <= self.attack_range + 3 and cooldown_remaining < 2:
                # burrow to attack
                self.burrow(unit)
                return True
            elif closest_distance <= self.attack_range + 6 and cooldown_remaining < 2 and new_target:
                unit.move(new_target)
                return True
            sieged_tanks = self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED)
            if new_target and sieged_tanks:
                closest_tank_to_enemy = self.closest_unit_to_unit(new_target, sieged_tanks)
                if closest_tank_to_enemy:
                    burrow_position = closest_tank_to_enemy.position.towards(new_target.position, closest_tank_to_enemy.radius + 1)
                    if unit.distance_to_squared(burrow_position) > 4:
                        unit.move(burrow_position)
                    elif cooldown_remaining < 2:
                        self.burrow(unit)
                    return True
        return False

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

    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> bool:
        # just use auto attack
        return unit.tag in self.burrowed_tags
