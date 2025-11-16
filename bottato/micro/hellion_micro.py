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

        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if self._retreat_to_tank(unit, can_attack):
            return True

        bonus_distance = 4
        attackable_enemies = self.bot.enemy_units.filter(lambda u: u.can_be_attacked and u.armor < 10) + self.bot.enemy_structures.of_type(self.offensive_structure_types)
        candidates = UnitTypes.in_attack_range_of(unit, attackable_enemies, bonus_distance)
        if len(candidates) == 0:
            candidates = UnitTypes.in_attack_range_of(unit, self.bot.enemy_structures, bonus_distance)
        if not candidates:
            return False

        if can_attack:
            closest_target = candidates.closest_to(unit)
            unit.attack(closest_target)
            return True
        
        return self._stay_at_max_range(unit, candidates)
