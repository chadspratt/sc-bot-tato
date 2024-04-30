from __future__ import annotations
import math
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2

from ..mixins import GeometryMixin


class BaseUnitMicro(GeometryMixin):
    def __init__(self, unit: Unit, bot: BotAI):
        self.unit = unit
        self.bot: BotAI = bot

    def retreat(self, health_threshold: float) -> bool:
        if self.unit.health_percentage > health_threshold:
            return False

        attack_range_buffer = 2
        threats = [enemy_unit for enemy_unit in self.bot.all_enemy_units
                   if enemy_unit.target_in_range(self.unit, attack_range_buffer)]
        if not threats:
            return False

        retreat_vector = Point2([0, 0])

        total_potential_damage = 0.0
        for threat in threats:
            total_potential_damage += threat.calculate_damage_vs_target(self.unit)[0]
            retreat_vector += (self.unit.position - threat.position).normalized
        # check if incoming damage will bring unit below health threshold
        if (self.unit.health - total_potential_damage) / self.unit.health_max > health_threshold:
            return False
        map_center_vector = self.bot.game_info.map_center - self.unit.position
        retreat_vector = retreat_vector + map_center_vector.normalized

        logger.info(f"unit {self.unit} retreating from {threats} in direction {retreat_vector}")
        retreat_position = self.unit.position + retreat_vector
        is_pathable = self.bot.in_map_bounds if self.unit.is_flying else self.bot.in_pathing_grid
        position_attempts = 0
        while not is_pathable(retreat_position):
            position_attempts += 1
            if position_attempts > 10:
                # can't find a position to retreat to
                return False
            retreat_position = self.unit.position.towards_with_random_angle(retreat_position, 1, math.pi / 3)

        self.unit.move(self.unit.position + retreat_vector)
        return True

    def attack_something(self):
        if self.unit.weapon_cooldown == 0:
            targets = self.bot.all_enemy_units.in_attack_range_of(self.unit)
            if targets:
                target = targets.sorted(key=lambda enemy_unit: enemy_unit.health).first
                self.unit.attack(target)
                logger.info(f"unit {self.unit} attacking enemy {target}")
                return target
        return None

    def scout(self, scouting_location: Point2):
        logger.info(f"scout {self.unit} health {self.unit.health}/{self.unit.health_max} ({self.unit.health_percentage}) health")

        if self.retreat(health_threshold=1.0):
            pass
        elif self.attack_something():
            pass
        elif self.retreat(health_threshold=0.75):
            pass
        else:
            logger.info(f"scout {self.unit} moving to updated assignment {scouting_location}")
            self.unit.move(scouting_location.position)
