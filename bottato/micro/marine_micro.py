from __future__ import annotations

from sc2.position import Point2
from sc2.unit import Unit
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

from bottato.enums import UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, timed_async
from bottato.unit_types import UnitTypes


class MarineMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.51
    last_stim_time: dict[int, float] = {}
    stim_researched: bool = False
    attack_range: float = 5.0
    time_in_frames_to_attack: float = 0.3 * 22.4  # 0.3 seconds

    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> UnitMicroType:
        if unit.health <= 35:
            return UnitMicroType.NONE
        if not self.stim_researched:
            if UpgradeId.STIMPACK in self.bot.state.upgrades:
                self.stim_researched = True
            else:
                return UnitMicroType.NONE
        if self.is_stimmed(unit):
            return UnitMicroType.NONE
        
        closest_enemy, closest_distance = self.enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=UnitTypes.WORKER_TYPES)
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if closest_distance <= self.attack_range:
            if self._retreat_to_tank(unit, can_attack):
                return UnitMicroType.RETREAT
            if closest_enemy and closest_enemy.age > 0:
                return UnitMicroType.NONE
            unit(AbilityId.EFFECT_STIM_MARINE)
            self.last_stim_time[unit.tag] = self.bot.time
            return UnitMicroType.USE_ABILITY
        enemy_sieged_tanks = self.bot.enemy_units(UnitTypeId.SIEGETANKSIEGED)
        if enemy_sieged_tanks and enemy_sieged_tanks.closest_distance_to(unit) < 7:
            # stim to rush sieged tanks
            unit(AbilityId.EFFECT_STIM_MARINE)
            self.last_stim_time[unit.tag] = self.bot.time
            return UnitMicroType.USE_ABILITY
        return UnitMicroType.NONE
    
    def is_stimmed(self, unit: Unit) -> bool:
        return unit.tag in self.last_stim_time and self.bot.time - self.last_stim_time[unit.tag] < 11

    @timed_async
    async def _retreat(self, unit: Unit, health_threshold: float) -> UnitMicroType:
        if unit.health_percentage < 0.7:
            if self._retreat_to_medivac(unit) != UnitMicroType.NONE:
                return UnitMicroType.RETREAT
            return await super()._retreat(unit, health_threshold)
        elif unit.tag in self.healing_unit_tags:
            if unit.health_percentage < 0.9:
                return self._retreat_to_medivac(unit)
            else:
                self.healing_unit_tags.remove(unit.tag)
        return UnitMicroType.NONE
