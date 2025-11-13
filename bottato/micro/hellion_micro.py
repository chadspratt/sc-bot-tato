from __future__ import annotations
from loguru import logger

from sc2.unit import Unit

from bottato.unit_types import UnitTypes
from bottato.mixins import GeometryMixin
from bottato.micro.base_unit_micro import BaseUnitMicro


class HellionMicro(BaseUnitMicro, GeometryMixin):
    attack_health = 0.4

    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        if force_move:
            return False
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        if unit.health_percentage < health_threshold:
            return False

        if self._retreat_to_tank(unit):
            return True

        bonus_distance = 4
        candidates = UnitTypes.in_attack_range_of(unit, self.bot.enemy_units, bonus_distance).filter(
            lambda unit: unit.can_be_attacked and unit.armor < 10)
        if len(candidates) == 0:
            candidates = UnitTypes.in_attack_range_of(unit, self.bot.enemy_structures, bonus_distance)
        if not candidates:
            return False

        if unit.weapon_cooldown <= self.time_in_frames_to_attack:
            closest_target = candidates.closest_to(unit)
            return self._kite(unit, closest_target)
        
        return self._stay_at_max_range(unit, candidates)
