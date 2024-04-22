from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2


class BaseUnitMicro:
    def __init__(self, unit: Unit, bot: BotAI):
        self.unit = unit
        self.bot: BotAI = bot

    def get_unit_micro(unit: Unit, bot: BotAI) -> BaseUnitMicro:
        return BaseUnitMicro(unit, bot)

    def retreat(self):
        attack_range_buffer = 2
        if self.unit.is_flying:
            threats = [enemy_unit for enemy_unit in self.bot.all_enemy_units
                       if enemy_unit.can_attack_air
                       and enemy_unit.air_range + attack_range_buffer > self.unit.distance_to(enemy_unit)]
        else:
            threats = [enemy_unit for enemy_unit in self.bot.all_enemy_units
                       if enemy_unit.can_attack_ground
                       and enemy_unit.ground_range + attack_range_buffer > self.unit.distance_to(enemy_unit)]
        retreat_vector = Point2([0, 0])
        map_center_vector = self.bot.game_info.map_center - self.unit.position
        if threats:
            for threat in threats:
                retreat_vector += self.unit.position - threat.position
            retreat_vector = retreat_vector.normalized * 2 + (map_center_vector).normalized
        else:
            retreat_vector = map_center_vector
        logger.info(f"unit {self.unit} retreating from {threats} in direction {retreat_vector}")
        self.unit.move(self.unit.position + retreat_vector)

    def attack_something(self):
        if self.unit.weapon_cooldown == 0:
            targets = self.bot.all_enemy_units.in_attack_range_of(self.unit)
            if targets:
                target = targets.sorted(key=lambda enemy_unit: enemy_unit.health).first
                self.unit.attack(target)
                logger.info(f"unit {self.unit} attacking enemy {target}")
                return target
        return None
