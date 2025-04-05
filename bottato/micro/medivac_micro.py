from __future__ import annotations
from loguru import logger

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base_unit_micro import BaseUnitMicro
from ..enemy import Enemy
from ..mixins import GeometryMixin


class MedivacMicro(BaseUnitMicro, GeometryMixin):
    heal_cost = 1
    heal_start_cost = 5
    heal_range = 4
    ability_health = 0.5
    pick_up_range = 2

    stopped_for_healing: set[int] = set()

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float) -> bool:
        stopped = False
        if unit.health_percentage >= health_threshold:
            # should get once per step instead of per medivac
            injured_bio = self.bot.units.filter(lambda unit: unit.is_biological and unit.health_percentage < 1.0).closer_than(20, unit)
            if injured_bio and self.heal_available(unit):
                if injured_bio.closer_than(self.heal_range, unit):
                    unit.stop()
                    logger.info(f"{unit} stopping to heal")
                    stopped = True
                else:
                    nearest_injured = injured_bio.closest_to(unit)
                    logger.info(f"{unit} moving to heal {nearest_injured}")
                    unit.move(nearest_injured)
        else:
            logger.info(f"{unit} below health threshold to heal {unit.health_percentage} < {health_threshold}")
        if stopped:
            self.stopped_for_healing.add(unit.tag)
        elif unit.tag in self.stopped_for_healing:
            self.stopped_for_healing.remove(unit.tag)
        return unit.tag in self.bot.unit_tags_received_action

    def attack_something(self, unit: Unit, health_threshold: float) -> bool:
        # doesn't have an attack
        return False

    def heal_available(self, unit: Unit) -> bool:
        if unit.tag in self.stopped_for_healing:
            return unit.energy >= self.heal_cost
        else:
            return unit.energy >= self.heal_start_cost
