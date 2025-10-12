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

    async def use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        return False

    async def retreat(self, unit: Unit, health_threshold: float) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        threats = self.enemy.threats_to(unit)

        if not threats:
            if unit.health_percentage >= health_threshold:
                return False
            else:
                if unit.is_mechanical:
                    repairers = self.bot.workers.filter(lambda unit: unit.is_repairing) or self.bot.workers
                    if repairers:
                        repairers = repairers.filter(lambda worker: worker.tag != unit.tag)
                    if repairers:
                        unit.move(repairers.closest_to(unit))
                    else:
                        return False
                else:
                    medivacs = self.bot.units.of_type(UnitTypeId.MEDIVAC)
                    if medivacs:
                        unit.move(medivacs.closest_to(unit))
                    else:
                        unit.move(self.bot.game_info.player_start_location)
            return True

        # check if incoming damage will bring unit below health threshold
        total_potential_damage = sum([threat.calculate_damage_vs_target(unit)[0] for threat in threats])
        if (unit.health - total_potential_damage) / unit.health_max >= health_threshold:
            return False
        else:
            avg_threat_position = threats.center
            retreat_position = unit.position.towards(avg_threat_position, -5).towards(self.bot.start_location, 2)
            if self.bot.in_pathing_grid(retreat_position):
                unit.move(retreat_position)
            else:
                threat_to_unit_vector = (unit.position - avg_threat_position).normalized
                tangent_vector = Point2((-threat_to_unit_vector.y, threat_to_unit_vector.x)) * unit.movement_speed
                circle_around_positions = [unit.position + tangent_vector, unit.position - tangent_vector]
                circle_around_positions.sort(key=lambda pos: pos.distance_to(self.bot.start_location))
                unit.move(circle_around_positions[0].towards(self.bot.start_location, 2))
        return True

    def attack_something(self, unit: Unit, health_threshold: float, targets: Units = None, force_move: bool = False) -> bool:
        if force_move:
            return False
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        if unit.health_percentage < health_threshold:
            return False
        candidates = []
        if targets:
            candidates = targets.filter(lambda unit: not unit.is_structure and unit.armor < 10)
            if len(candidates) == 0:
                candidates = targets
        else:
            candidates = self.bot.enemy_units.in_attack_range_of(unit).filter(lambda unit: unit.can_be_attacked and unit.armor < 10)
            if len(candidates) == 0:
                candidates = self.bot.enemy_structures.in_attack_range_of(unit)

        tank_to_retreat_to = self.tank_to_retreat_to(unit)
        if tank_to_retreat_to:
            unit.move(unit.position.towards(tank_to_retreat_to.position, 2))
            return True

        if not candidates:
            return False

        if unit.weapon_cooldown <= 0.25:
            lowest_target = candidates.sorted(key=lambda enemy_unit: enemy_unit.health + enemy_unit.shield).first
            unit.attack(lowest_target)
        else:
            self.stay_at_max_range(unit, candidates)
        return True

    def stay_at_max_range(self, unit: Unit, targets: Units = None):
        nearest_target = targets.closest_to(unit)
        # move away if weapon on cooldown
        attack_range = unit.ground_range
        if nearest_target.is_flying:
            attack_range = unit.air_range
        elif nearest_target.type_id == UnitTypeId.SIEGETANKSIEGED:
            if unit.distance_to(nearest_target) < 8:
                # dive on sieged tanks
                attack_range = 0
            else:
                attack_range = 14
        future_enemy_position = self.enemy.get_predicted_position(nearest_target, unit.weapon_cooldown)
        target_position = future_enemy_position.towards(unit, attack_range)
        unit.move(target_position)
        # logger.debug(f"unit {unit}({unit.position}) staying at attack range {attack_range} to {nearest_target}({nearest_target.position}) at {target_position}")
        
    def tank_to_retreat_to(self, unit: Unit) -> Unit | None:
        excluded_enemy_types = [
            UnitTypeId.PROBE,
            UnitTypeId.SCV,
            UnitTypeId.DRONE,
            UnitTypeId.DRONEBURROWED,
            UnitTypeId.MULE,
            UnitTypeId.OBSERVER,
            UnitTypeId.LARVA,
            UnitTypeId.EGG
        ]
        tanks = self.bot.units.of_type((UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED))
        if not tanks:
            return None

        close_enemies = self.bot.enemy_units.closer_than(15, unit).filter(
            lambda u: u.type_id not in excluded_enemy_types and not u.is_flying and u.can_attack_ground and u.unit_alias != UnitTypeId.CHANGELING)
        if len(close_enemies) < 8:
            return None
        
        closest_enemy = close_enemies.closest_to(unit)
        if not closest_enemy or closest_enemy.is_flying:
            return None

        nearest_tank = tanks.closest_to(unit)
        tank_to_enemy_distance = self.distance(nearest_tank, closest_enemy)
        if tank_to_enemy_distance > 13.5 and tank_to_enemy_distance < 30:
            return nearest_tank
        return None

    async def move(self, unit: Unit, target: Point2, force_move: bool = False) -> None:
        if unit.tag in self.bot.unit_tags_received_action:
            return
        if await self.use_ability(unit, target, health_threshold=self.ability_health, force_move=force_move):
            logger.debug(f"unit {unit} used ability")
        elif self.attack_something(unit, health_threshold=self.attack_health, force_move=force_move):
            logger.debug(f"unit {unit} attacked something")
        elif force_move:
            unit.move(target)
            logger.debug(f"unit {unit} moving to {target}")
        elif await self.retreat(unit, health_threshold=self.retreat_health):
            logger.debug(f"unit {unit} retreated")
        else:
            unit.move(target)
            logger.debug(f"unit {unit} moving to {target}")

    async def scout(self, unit: Unit, scouting_location: Point2):
        logger.debug(f"scout {unit} health {unit.health}/{unit.health_max} ({unit.health_percentage}) health")

        if await self.use_ability(unit, scouting_location, health_threshold=1.0):
            pass
        elif await self.retreat(unit, health_threshold=1.0):
            pass
        elif self.attack_something(unit, health_threshold=0.0):
            pass
        elif await self.retreat(unit, health_threshold=0.75):
            pass
        else:
            logger.debug(f"scout {unit} moving to updated assignment {scouting_location}")
            unit.move(scouting_location)
