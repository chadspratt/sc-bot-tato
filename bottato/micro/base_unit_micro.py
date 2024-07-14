from __future__ import annotations
# import math
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2

from ..mixins import GeometryMixin
from ..enemy import Enemy


class BaseUnitMicro(GeometryMixin):
    def __init__(self, bot: BotAI):
        self.bot: BotAI = bot

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        return False

    async def retreat(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        if unit.health_percentage > health_threshold:
            return False

        threats = enemy.threats_to(unit)
        # threats = [enemy_unit for enemy_unit in self.bot.all_enemy_units
        #            if enemy_unit.target_in_range(unit)]
        if not threats:
            return False

        # retreat_vector = Point2([0, 0])

        total_potential_damage = 0.0
        for threat in threats:
            threat_damage = threat.calculate_damage_vs_target(unit)[0]
            total_potential_damage += threat_damage
            # retreat_vector += (unit.position - threat.position).normalized * threat_damage
        # check if incoming damage will bring unit below health threshold
        if (unit.health - total_potential_damage) / unit.health_max > health_threshold:
            return False
        # map_center_vector = self.bot.game_info.map_center - unit.position
        # retreat_vector = retreat_vector + map_center_vector.normalized

        # logger.info(f"unit {unit} retreating from {threats} in direction {retreat_vector}")
        # desired_position = unit.position + retreat_vector
        # attempted_position = unit.position.towards(desired_position, 5)
        # is_pathable = self.bot.in_map_bounds if unit.is_flying else self.bot.in_pathing_grid
        # position_attempts = 0
        # max_attempts = 10
        # min_deflection = math.pi / 5
        # max_deflection = math.pi / 2
        # deflection_range = max_deflection - min_deflection
        # while not is_pathable(attempted_position):
        #     deflection = min_deflection + deflection_range * position_attempts / max_attempts
        #     position_attempts += 1
        #     if position_attempts > max_attempts:
        #         # can't find a position to retreat to
        #         return False
        #     attempted_position = unit.position.towards_with_random_angle(desired_position, 5, deflection)
        # unit.move(unit.position + retreat_vector)
        logger.info(f"{unit} retreating")
        unit.move(self.bot.game_info.player_start_location)

        return True

    def attack_something(self, unit: Unit) -> bool:
        targets = self.bot.all_enemy_units.in_attack_range_of(unit)
        if targets:
            nearest_target = targets.sorted(key=lambda enemy_unit: enemy_unit.health).first
            if unit.weapon_cooldown == 0:
                unit.attack(nearest_target)
                logger.info(f"unit {unit} attacking enemy {nearest_target}")
                return True
            else:
                attack_range = unit.ground_range
                if nearest_target.is_flying:
                    attack_range = unit.air_range
                unit.move(nearest_target.position.towards(unit, attack_range - 0.5))
                logger.info(f"unit {unit} staying at attack range to {nearest_target}")
        return False

    async def move(self, unit: Unit, target: Point2, enemy: Enemy) -> None:
        if await self.use_ability(unit, enemy, health_threshold=0.0):
            logger.debug(f"unit {unit} used ability")
        elif await self.retreat(unit, enemy, health_threshold=0.0):
            logger.debug(f"unit {unit} retreated")
        elif self.attack_something(unit):
            logger.debug(f"unit {unit} attacked something")
        else:
            unit.move(target)
            logger.debug(f"unit {unit} moving to {target}")

    async def scout(self, unit: Unit, scouting_location: Point2, enemy: Enemy):
        logger.info(f"scout {unit} health {unit.health}/{unit.health_max} ({unit.health_percentage}) health")

        if await self.use_ability(unit, enemy, health_threshold=1.0):
            pass
        elif await self.retreat(unit, enemy, health_threshold=1.0):
            pass
        elif self.attack_something(unit):
            pass
        elif await self.retreat(unit, enemy, health_threshold=0.75):
            pass
        else:
            logger.info(f"scout {unit} moving to updated assignment {scouting_location}")
            unit.move(scouting_location)
