from __future__ import annotations
from loguru import logger

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId
from sc2.constants import UnitTypeId

from bottato.unit_types import UnitTypes
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin


class MarineMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.51
    last_stim_time: dict[int, int] = {}
    stim_researched: bool = False
    attack_range: float = 5.0
    time_in_frames_to_attack: float = 0.3 * 22.4  # 0.3 seconds

    excluded_ability_unit_types: set[UnitTypeId] = set((
        UnitTypeId.PROBE,
        UnitTypeId.SCV,
        UnitTypeId.DRONE,
        UnitTypeId.DRONEBURROWED,
        UnitTypeId.MULE,
    ))

    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if unit.health <= 35:
            return False
        if not self.stim_researched:
            if self.bot.already_pending_upgrade(UpgradeId.STIMPACK) == 1:
                self.stim_researched = True
            else:
                return False
        if self.is_stimmed(unit):
            return False
        
        closest_enemy, closest_distance = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=self.excluded_ability_unit_types)
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if closest_distance <= self.attack_range:
            if self._retreat_to_tank(unit, can_attack):
                return True
            unit(AbilityId.EFFECT_STIM_MARINE)
            self.last_stim_time[unit.tag] = self.bot.time
            return True
        enemy_sieged_tanks = self.bot.enemy_units(UnitTypeId.SIEGETANKSIEGED)
        if enemy_sieged_tanks and enemy_sieged_tanks.closest_distance_to(unit) < 7:
            # stim to rush sieged tanks
            unit(AbilityId.EFFECT_STIM_MARINE)
            self.last_stim_time[unit.tag] = self.bot.time
            return True
        return False
    
    def is_stimmed(self, unit: Unit) -> bool:
        return unit.tag in self.last_stim_time and self.bot.time - self.last_stim_time[unit.tag] < 11
    
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        attackable_enemies = self.bot.enemy_units.filter(lambda u: u.can_be_attacked and u.armor < 10) \
            + self.bot.enemy_structures.of_type(self.offensive_structure_types)
        candidates = UnitTypes.in_attack_range_of(unit, attackable_enemies)
        if len(candidates) == 0:
            candidates = UnitTypes.in_attack_range_of(unit, self.bot.enemy_structures)

        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if candidates and can_attack:
            lowest_target = candidates.sorted(key=lambda enemy_unit: enemy_unit.health).first
            unit.attack(lowest_target)
            return True
        elif unit.health_percentage >= health_threshold:
            if not self.is_stimmed(unit) and self._retreat_to_tank(unit, can_attack):
                return True

            if candidates:
                return self._stay_at_max_range(unit, candidates)
        return False

    async def _retreat(self, unit: Unit, health_threshold: float) -> bool:
        if unit.health_percentage < 0.7:
            return self._retreat_to_medivac(unit)
        elif unit.tag in self.healing_unit_tags:
            if unit.health_percentage < 0.9:
                return self._retreat_to_medivac(unit)
            else:
                self.healing_unit_tags.remove(unit.tag)
        return False
