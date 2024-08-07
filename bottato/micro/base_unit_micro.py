from __future__ import annotations
# import math
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2
from sc2.constants import UnitTypeId

from ..mixins import GeometryMixin
from ..enemy import Enemy


class BaseUnitMicro(GeometryMixin):
    ability_health: float = 0.1
    attack_health: float = 0.1
    retreat_health: float = 0.75

    def __init__(self, bot: BotAI):
        self.bot: BotAI = bot

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        return False

    async def retreat(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        do_retreat = False
        if unit.health_percentage < health_threshold:
            # already below min
            do_retreat = True
        else:
            threats = enemy.threats_to(unit)
            if not threats:
                return False

        # retreat_vector = Point2([0, 0])

            total_potential_damage = 0.0
            for threat in threats:
                threat_damage = threat.calculate_damage_vs_target(unit)[0]
                total_potential_damage += threat_damage
            # retreat_vector += (unit.position - threat.position).normalized * threat_damage
        # check if incoming damage will bring unit below health threshold
            if (unit.health - total_potential_damage) / unit.health_max < health_threshold:
                do_retreat = True
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
        if do_retreat:
            logger.info(f"{unit} retreating")
            if unit.is_mechanical:
                unit.move(self.bot.workers.closest_to(unit))
            else:
                medivacs = self.bot.units.of_type(UnitTypeId.MEDIVAC)
                if medivacs:
                    unit.move(medivacs.closest_to(unit))
                else:
                    unit.move(self.bot.game_info.player_start_location)

        return do_retreat

    def attack_something(self, unit: Unit, health_threshold: float) -> bool:
        if unit.health_percentage < health_threshold:
            return False
        targets = self.bot.all_enemy_units.in_attack_range_of(unit)
        if targets:
            if unit.weapon_cooldown == 0:
                lowest_target = targets.sorted(key=lambda enemy_unit: enemy_unit.health).first
                unit.attack(lowest_target)
                logger.info(f"unit {unit} attacking enemy {lowest_target}({lowest_target.position})")
                return True
            else:
                nearest_target = targets.closest_to(unit)
                attack_range = unit.ground_range
                if nearest_target.is_flying:
                    attack_range = unit.air_range
                target_position = nearest_target.position.towards(unit, attack_range - 0.5)
                unit.move(target_position)
                logger.info(f"unit {unit}({unit.position}) staying at attack range {attack_range} to {nearest_target}({nearest_target.position}) at {target_position}")
                return True
        return False

    async def move(self, unit: Unit, target: Point2, enemy: Enemy) -> None:
        if await self.use_ability(unit, enemy, health_threshold=self.ability_health):
            logger.debug(f"unit {unit} used ability")
        elif self.attack_something(unit, health_threshold=self.attack_health):
            logger.debug(f"unit {unit} attacked something")
        elif await self.retreat(unit, enemy, health_threshold=self.retreat_health):
            logger.debug(f"unit {unit} retreated")
        else:
            unit.move(target)
            logger.debug(f"unit {unit} moving to {target}")

    async def scout(self, unit: Unit, scouting_location: Point2, enemy: Enemy):
        logger.info(f"scout {unit} health {unit.health}/{unit.health_max} ({unit.health_percentage}) health")

        if await self.use_ability(unit, enemy, health_threshold=1.0):
            pass
        elif await self.retreat(unit, enemy, health_threshold=1.0):
            pass
        elif self.attack_something(unit, health_threshold=0.0):
            pass
        elif await self.retreat(unit, enemy, health_threshold=0.75):
            pass
        else:
            logger.info(f"scout {unit} moving to updated assignment {scouting_location}")
            unit.move(scouting_location)
