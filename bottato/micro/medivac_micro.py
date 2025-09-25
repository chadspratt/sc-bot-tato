from __future__ import annotations
from loguru import logger

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId


from .base_unit_micro import BaseUnitMicro
from ..enemy import Enemy
from ..mixins import GeometryMixin


class MedivacMicro(BaseUnitMicro, GeometryMixin):
    heal_cost = 1
    heal_start_cost = 5
    heal_range = 4
    ability_health = 0.5
    pick_up_range = 2
    health_threshold_for_healing = 0.75

    stopped_for_healing: set[int] = set()
    injured_bio: Units = None
    last_afterburner_time: dict[int, float] = {}

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        threats = enemy.threats_to(unit, 5)
        if unit.health_percentage < self.health_threshold_for_healing and threats:
            if unit.tag not in self.last_afterburner_time or self.bot.time - self.last_afterburner_time[unit.tag] > 14.0:
                unit(AbilityId.EFFECT_MEDIVACIGNITEAFTERBURNERS)
                self.last_afterburner_time[unit.tag] = self.bot.time
            return False
        if not self.heal_available(unit):
            return False
        if force_move and threats:
            return False
        
        # refresh list of injured bio once per iteration
        if self.injured_bio is None or not self.injured_bio or self.injured_bio.first.age != 0:
            self.injured_bio = self.bot.units.filter(lambda u: u.is_biological and u.health_percentage < 1.0)

        heal_candidates = self.injured_bio.closer_than(20, unit)
        if heal_candidates:
            nearest_injured = heal_candidates.closest_to(unit)
            if self.distance(unit, nearest_injured) <= self.heal_range:
                unit.stop()
                self.stopped_for_healing.add(unit.tag)
            else:
                unit.move(nearest_injured)
                if unit.tag in self.stopped_for_healing:
                    self.stopped_for_healing.remove(unit.tag)

        return unit.tag in self.bot.unit_tags_received_action

    def attack_something(self, unit: Unit, enemy: Enemy, health_threshold: float, force_move: bool = False) -> bool:
        # doesn't have an attack
        return False

    def heal_available(self, unit: Unit) -> bool:
        if unit.tag in self.stopped_for_healing:
            return unit.energy >= self.heal_cost
        else:
            return unit.energy >= self.heal_start_cost
