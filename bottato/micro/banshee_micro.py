from __future__ import annotations

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.ability_id import AbilityId
from .base_unit_micro import BaseUnitMicro
from ..enemy import Enemy
from ..mixins import GeometryMixin


class BansheeMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.51

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if await self.bot.can_cast(unit, AbilityId.BEHAVIOR_CLOAKON_BANSHEE) and self.enemy.threats_to(unit):
            unit(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)

    def attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        if unit.health_percentage < health_threshold:
            return False
        nearby_enemies = self.bot.enemy_units.closer_than(15, unit)
        targets = nearby_enemies.filter(lambda u: not u.is_flying)
        threats = nearby_enemies.filter(lambda u: u.can_attack_air)
        if targets:
            if not threats:
                target = targets.closest_to(unit)
                unit.attack(target)
                return True
            elif unit.weapon_cooldown <= self.time_in_frames_to_attack and len(threats) < 4:
                attackable_threats = threats.filter(lambda u: not u.is_flying)
                if attackable_threats:
                    target = attackable_threats.closest_to(unit)
                    unit.attack(target)
                    return True
                else:
                    target = targets.closest_to(unit)
                    unit.attack(target)
                    return True
            tank_to_retreat_to = self.tank_to_retreat_to(unit)
            if tank_to_retreat_to:
                unit.move(unit.position.towards(tank_to_retreat_to.position, 2))
                return True
            self.stay_at_max_range(unit, nearby_enemies)
            return True
        return False
