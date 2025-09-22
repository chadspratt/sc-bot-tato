from __future__ import annotations
from loguru import logger

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.ability_id import AbilityId



from .base_unit_micro import BaseUnitMicro
from sc2.constants import UnitTypeId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class MarineMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.51
    healing_unit_tags = set()
    last_stim_time: dict[int, int] = {}
    stim_researched: bool = False
    attack_range: float = 5.0 

    def __init__(self, bot: BotAI, enemy: Enemy):
        super().__init__(bot, enemy)

    async def use_ability(self, unit: Unit, enemy: Enemy, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if unit.health <= 35:
            return False
        if not self.stim_researched:
            if self.bot.already_pending_upgrade(UpgradeId.STIMPACK) == 1:
                self.stim_researched = True
            else:
                return False
        if self.is_stimmed(unit):
            return False
        
        excluded_enemy_types = [
            UnitTypeId.PROBE,
            UnitTypeId.SCV,
            UnitTypeId.DRONE,
            UnitTypeId.DRONEBURROWED,
            UnitTypeId.MULE
        ]
        closest_enemy, closest_distance = enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=excluded_enemy_types)
        tank_to_retreat_to = self.tank_to_retreat_to(unit, enemy, closest_enemy)
        if closest_distance <= self.attack_range and tank_to_retreat_to is None:
            unit(AbilityId.EFFECT_STIM_MARINE)
            self.last_stim_time[unit.tag] = self.bot.time
            return True
        return False
    
    def is_stimmed(self, unit: Unit) -> bool:
        return unit.tag in self.last_stim_time and self.bot.time - self.last_stim_time[unit.tag] < 11
    
    def attack_something(self, unit: Unit, enemy: Enemy, health_threshold: float, targets: Units = None, force_move: bool = False) -> bool:
        if unit.health_percentage < health_threshold:
            return False
        # if unit.weapon_cooldown != 0:
        #     return False
        
        candidates = []
        if targets:
            candidates = targets.filter(lambda unit: not unit.is_structure)
            if len(candidates) == 0:
                candidates = targets
        else:
            candidates = self.bot.enemy_units.in_attack_range_of(unit)
            if len(candidates) == 0:
                candidates = self.bot.enemy_structures.in_attack_range_of(unit)

        if not candidates:
            return False
        
        if unit.weapon_cooldown == 0:
            if self.is_stimmed(unit):
                # attack if stimmed
                return self.attack_lowest_health(unit, candidates)
            else:
                tank_to_retreat_to = self.tank_to_retreat_to(unit, enemy)
                if tank_to_retreat_to:
                    # retreat to nearby tank if not stimmed
                    unit.move(unit.position.towards(tank_to_retreat_to.position, 2))
                    return True
                else:
                    return self.attack_lowest_health(unit, candidates)
        else:
            tank_to_retreat_to = self.tank_to_retreat_to(unit, enemy)
            if tank_to_retreat_to:
                # stay in range of tank
                unit.move(unit.position.towards(tank_to_retreat_to.position, 2))
                return True
            else:
                # stay at max attack range
                extra_range = -0.5
                if unit.weapon_cooldown > 1:
                    extra_range = 3
                nearest_target = candidates.closest_to(unit)
                attack_range = unit.ground_range
                if nearest_target.is_flying:
                    attack_range = unit.air_range
                target_position = nearest_target.position.towards(unit, attack_range + extra_range)
                unit.move(target_position)
                logger.info(f"unit {unit}({unit.position}) staying at attack range {attack_range} to {nearest_target}({nearest_target.position}) at {target_position}")
                return True
        
    def tank_to_retreat_to(self, unit: Unit, enemy: Enemy, closest_enemy: Unit = None) -> Unit | None:
        excluded_enemy_types = [
            UnitTypeId.PROBE,
            UnitTypeId.SCV,
            UnitTypeId.DRONE,
            UnitTypeId.DRONEBURROWED,
            UnitTypeId.MULE,
            UnitTypeId.OBSERVER
        ]
        if not closest_enemy:
            closest_enemy, closest_distance = enemy.get_closest_target(unit, include_structures=False, include_destructables=False, excluded_types=excluded_enemy_types)
        if not closest_enemy or closest_enemy.is_flying:
            return None
        tanks = self.bot.units.of_type((UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED))
        nearest_tank = tanks.closest_to(unit) if tanks else None
        tank_to_enemy_distance = self.distance(nearest_tank, closest_enemy) if nearest_tank and closest_enemy else 9999
        if tank_to_enemy_distance > 13.5 and tank_to_enemy_distance < 25:
            return nearest_tank
        return None
    
    def attack_lowest_health(self, unit: Unit, targets: Units) -> bool:
        lowest_target = targets.sorted(key=lambda enemy_unit: enemy_unit.health).first
        unit.attack(lowest_target)
        logger.debug(f"unit {unit} attacking enemy {lowest_target}({lowest_target.position})")
        return True

    async def retreat(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        if unit.health_percentage < 0.7:
            return self.retreat_to_medivac(unit)
        elif unit.tag in self.healing_unit_tags:
            if unit.health_percentage < 0.9:
                return self.retreat_to_medivac(unit)
            else:
                self.healing_unit_tags.remove(unit.tag)
        return False

    def retreat_to_medivac(self, unit: Unit) -> bool:
        medivacs = self.bot.units.filter(lambda unit: unit.type_id == UnitTypeId.MEDIVAC and unit.energy > 5)
        if medivacs:
            nearest_medivac = medivacs.closest_to(unit)
            unit.move(nearest_medivac)
            logger.debug(f"{unit} marine retreating to heal at {nearest_medivac} hp {unit.health_percentage}")
            self.healing_unit_tags.add(unit.tag)
        elif self.bot.townhalls:
            unit.move(self.bot.townhalls.closest_to(unit))
        else:
            return False
        return True
