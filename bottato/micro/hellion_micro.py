from __future__ import annotations

from sc2.ids.buff_id import BuffId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.enums import UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, timed
from bottato.unit_types import UnitTypes


class HellionMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.4

    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> UnitMicroType:
        if unit.tag in self.bot.unit_tags_received_action:
            return UnitMicroType.NONE

        if self.last_targets_update_time != self.bot.time:
            self.last_targets_update_time = self.bot.time
            self.valid_targets = self.bot.enemy_units.filter(
                lambda u: UnitTypes.can_be_attacked(u, self.bot, self.enemy.get_enemies()) and u.armor < 10 and BuffId.NEURALPARASITE not in u.buffs
                ) + self.bot.enemy_structures

        if not self.valid_targets:
            return UnitMicroType.NONE
        nearby_enemies = self.valid_targets.closer_than(20, unit).sorted(lambda u: u.health + u.shield)
        if not nearby_enemies:
            return UnitMicroType.NONE
        
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if can_attack:
            bonus_distance = -2 if unit.health_percentage < health_threshold else 0
            if UnitTypes.range(unit) < 1:
                bonus_distance = 1
            # attack enemy in range
            attack_target = self._get_attack_target(unit, nearby_enemies, bonus_distance)
            if attack_target:
                self._attack(unit, attack_target)
                return UnitMicroType.ATTACK
        
        # don't attack if low health and there are threats
        if unit.health_percentage < health_threshold:
            return UnitMicroType.NONE
            
        # no enemy in range, stay near tanks
        if self._retreat_to_tank(unit, can_attack):
            return UnitMicroType.RETREAT
            
        if can_attack:
            # venture out to attack further enemy but don't chase too far
            if move_position is not None and move_position.manhattan_distance(unit.position) < 20:
                attack_target = self._get_attack_target(unit, nearby_enemies, 5)
                if attack_target:
                    unit.attack(attack_target)
                    return UnitMicroType.ATTACK
        elif self.valid_targets:
            defending_ramp = unit.position.manhattan_distance(self.bot.main_base_ramp.top_center) < 10
            buffer = -5 if defending_ramp else -1
            return self._stay_at_max_range(unit, self.valid_targets, buffer=buffer)

        return UnitMicroType.NONE
