from __future__ import annotations
# import math
from loguru import logger

from sc2.units import Units
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2
from sc2.constants import UnitTypeId

from bottato.mixins import GeometryMixin
from bottato.enemy import Enemy


class BaseUnitMicro(GeometryMixin):
    ability_health: float = 0.1
    attack_health: float = 0.1
    retreat_health: float = 0.75

    def __init__(self, bot: BotAI, enemy: Enemy):
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        return False

    async def retreat(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        do_retreat = False
        if unit.health_percentage < health_threshold:
            # already below min
            do_retreat = True
        else:
            threats = enemy.threats_to(unit, 3)
            if not threats:
                return False

            total_potential_damage = 0.0
            for threat in threats:
                threat_damage = threat.calculate_damage_vs_target(unit)[0]
                total_potential_damage += threat_damage
        # check if incoming damage will bring unit below health threshold
            if (unit.health - total_potential_damage) / unit.health_max < health_threshold:
                do_retreat = True 
        if do_retreat:
            logger.debug(f"{unit} retreating")
            if unit.is_mechanical:
                repairers = self.bot.workers.filter(lambda unit: unit.is_repairing) or self.bot.workers
                if repairers:
                    unit.move(repairers.closest_to(unit))
                else:
                    do_retreat = False
            else:
                medivacs = self.bot.units.of_type(UnitTypeId.MEDIVAC)
                if medivacs:
                    unit.move(medivacs.closest_to(unit))
                else:
                    unit.move(self.bot.game_info.player_start_location)

        return do_retreat

    def attack_something(self, unit: Unit, health_threshold: float, targets: Units = None) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        if unit.health_percentage < health_threshold:
            return False
        if unit.weapon_cooldown != 0:
            return False
        candidates = []
        if targets:
            candidates = targets.filter(lambda unit: not unit.is_structure)
            if len(candidates) == 0:
                candidates = targets
        else:
            candidates = self.bot.enemy_units.in_attack_range_of(unit)
            if len(candidates) == 0:
                candidates = self.bot.enemy_structures.in_attack_range_of(unit)

        if candidates:
            lowest_target = candidates.sorted(key=lambda enemy_unit: enemy_unit.health).first
            unit.attack(lowest_target)
            logger.debug(f"unit {unit} attacking enemy {lowest_target}({lowest_target.position})")
            return True
        return False

    async def move(self, unit: Unit, target: Point2, enemy: Enemy, force_move: bool = False) -> None:
        if unit.tag in self.bot.unit_tags_received_action:
            return
        if await self.use_ability(unit, enemy, target, health_threshold=self.ability_health, force_move=force_move):
            logger.debug(f"unit {unit} used ability")
        elif self.attack_something(unit, health_threshold=self.attack_health):
            logger.debug(f"unit {unit} attacked something")
        elif force_move:
            unit.move(target)
            logger.debug(f"unit {unit} moving to {target}")
        elif await self.retreat(unit, enemy, health_threshold=self.retreat_health):
            logger.debug(f"unit {unit} retreated")
        else:
            unit.move(target)
            logger.debug(f"unit {unit} moving to {target}")

    async def scout(self, unit: Unit, scouting_location: Point2, enemy: Enemy):
        logger.debug(f"scout {unit} health {unit.health}/{unit.health_max} ({unit.health_percentage}) health")

        if await self.use_ability(unit, enemy, scouting_location, health_threshold=1.0):
            pass
        elif await self.retreat(unit, enemy, health_threshold=1.0):
            pass
        elif self.attack_something(unit, health_threshold=0.0):
            pass
        elif await self.retreat(unit, enemy, health_threshold=0.75):
            pass
        else:
            logger.debug(f"scout {unit} moving to updated assignment {scouting_location}")
            unit.move(scouting_location)
