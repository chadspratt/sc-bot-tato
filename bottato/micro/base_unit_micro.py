from __future__ import annotations
# import math
from loguru import logger

from sc2.units import Units
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2
from sc2.constants import UnitTypeId
from sc2.ids.effect_id import EffectId
from sc2.ids.ability_id import AbilityId

from bottato.mixins import GeometryMixin
from bottato.enemy import Enemy


class BaseUnitMicro(GeometryMixin):
    ability_health: float = 0.1
    attack_health: float = 0.1
    retreat_health: float = 0.75
    time_in_frames_to_attack: float = 0.25 * 22.4  # 0.3 seconds
    
    damaging_effects = [
        EffectId.PSISTORMPERSISTENT,
        # EffectId.GUARDIANSHIELDPERSISTENT,
        # EffectId.TEMPORALFIELDGROWINGBUBBLECREATEPERSISTENT,
        # EffectId.TEMPORALFIELDAFTERBUBBLECREATEPERSISTENT,
        EffectId.THERMALLANCESFORWARD,
        # EffectId.SCANNERSWEEP,
        EffectId.NUKEPERSISTENT,
        EffectId.LIBERATORTARGETMORPHDELAYPERSISTENT,
        EffectId.LIBERATORTARGETMORPHPERSISTENT,
        EffectId.BLINDINGCLOUDCP,
        EffectId.RAVAGERCORROSIVEBILECP,
        EffectId.LURKERMP,
        'KD8CHARGE',
    ]
    def __init__(self, bot: BotAI, enemy: Enemy):
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy

    def avoid_effects(self, unit: Unit, force_move: bool) -> bool:
        # avoid damaging effects
        effects_to_avoid = []
        for effect in self.bot.state.effects:
            if effect.id not in self.damaging_effects:
                continue
            if effect.id in (EffectId.LIBERATORTARGETMORPHDELAYPERSISTENT, EffectId.LIBERATORTARGETMORPHPERSISTENT):
                if effect.is_mine or unit.is_flying:
                    continue
                if unit.type_id == UnitTypeId.SIEGETANKSIEGED and force_move:
                    unit(AbilityId.UNSIEGE_UNSIEGE)
                    return True
            safe_distance = (effect.radius + unit.radius + 1) ** 2
            for position in effect.positions:
                if unit.position._distance_squared(position) < safe_distance:
                    effects_to_avoid.append(position)
        if effects_to_avoid:
            number_of_effects = len(effects_to_avoid)
            if number_of_effects == 1:
                # move directly away from effect
                new_position = unit.position.towards(effects_to_avoid[0], -2)
                unit.move(new_position)
                return True
            average_x = sum(p.x for p in effects_to_avoid) / number_of_effects
            average_y = sum(p.y for p in effects_to_avoid) / number_of_effects
            average_position = Point2((average_x, average_y))
            # move out of effect radius
            new_position = unit.position.towards(average_position, -2)
            unit.move(new_position)
            return True
        return False

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
            if unit.distance_to(self.bot.start_location) < avg_threat_position.distance_to(self.bot.start_location):
                unit.move(self.bot.start_location)
                return True
            retreat_position = unit.position.towards(avg_threat_position, -5).towards(self.bot.start_location, 2)
            if self.bot.in_pathing_grid(retreat_position):
                unit.move(retreat_position)
            else:
                if unit.position == avg_threat_position:
                    # avoid divide by zero
                    unit.move(self.bot.start_location)
                else:
                    threat_to_unit_vector = (unit.position - avg_threat_position).normalized
                    tangent_vector = Point2((-threat_to_unit_vector.y, threat_to_unit_vector.x)) * unit.movement_speed
                    circle_around_positions = [unit.position + tangent_vector, unit.position - tangent_vector]
                    circle_around_positions.sort(key=lambda pos: pos.distance_to(self.bot.start_location))
                    unit.move(circle_around_positions[0].towards(self.bot.start_location, 2))
        return True

    def attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        if force_move:
            return False
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        if unit.health_percentage < health_threshold:
            return False
        candidates = []

        candidates = self.bot.enemy_units.in_attack_range_of(unit).filter(lambda unit: unit.can_be_attacked and unit.armor < 10)
        if len(candidates) == 0:
            candidates = self.bot.enemy_structures.in_attack_range_of(unit)

        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if unit.is_flying and can_attack and candidates:
            threats = candidates.filter(lambda u: u.can_attack_air)
            if len(threats) < 4:
                if threats:
                    lowest_target = threats.sorted(key=lambda enemy_unit: enemy_unit.health + enemy_unit.shield).first
                    unit.attack(lowest_target)
                else:
                    lowest_target = candidates.sorted(key=lambda enemy_unit: enemy_unit.health + enemy_unit.shield).first
                    unit.attack(lowest_target)
                return True

        tank_to_retreat_to = self.tank_to_retreat_to(unit)
        if tank_to_retreat_to:
            unit.move(unit.position.towards(tank_to_retreat_to.position, 2))
            return True

        if not candidates:
            return False

        if can_attack:
            lowest_target = candidates.sorted(key=lambda enemy_unit: enemy_unit.health + enemy_unit.shield).first
            unit.attack(lowest_target)
        else:
            self.stay_at_max_range(unit, candidates)
        return True

    def stay_at_max_range(self, unit: Unit, targets: Units = None):
        # move away if weapon on cooldown
        nearest_target = targets.closest_to(unit)
        if not unit.is_flying:
            nearest_sieged_tank = None
            if nearest_target.type_id == UnitTypeId.SIEGETANKSIEGED:
                nearest_sieged_tank = nearest_target
            else:
                enemy_tanks = targets.of_type(UnitTypeId.SIEGETANKSIEGED)
                if enemy_tanks:
                    nearest_sieged_tank = enemy_tanks.closest_to(unit)

            if nearest_sieged_tank:
                distance_to_tank = unit.distance_to(nearest_sieged_tank)
                if distance_to_tank < 7:
                    # dive on sieged tanks
                    attack_range = 0
                    target_position = nearest_sieged_tank.position.towards(unit, attack_range)
                    unit.move(target_position)
                    return
                if distance_to_tank < 15:
                    attack_range = 14
                    target_position = nearest_sieged_tank.position.towards(unit, attack_range)
                    unit.move(target_position)
                    return

        attack_range = unit.ground_range
        if nearest_target.is_flying:
            attack_range = unit.air_range
        future_enemy_position = nearest_target.position
        if nearest_target.distance_to(unit) > attack_range / 2:
            future_enemy_position = self.enemy.get_predicted_position(nearest_target, unit.weapon_cooldown / 22.4)
        target_position = future_enemy_position.towards(unit, attack_range)
        unit.move(target_position)

    def retreat_to_medivac(self, unit: Unit) -> bool:
        medivacs = self.bot.units.filter(lambda unit: unit.type_id == UnitTypeId.MEDIVAC and unit.energy > 5 and unit.cargo_used == 0)
        if medivacs:
            nearest_medivac = medivacs.closest_to(unit)
            if unit.distance_to(nearest_medivac) > 4:
                unit.move(nearest_medivac)
            else:
                self.attack_something(unit, 0.0)
            logger.debug(f"{unit} marine retreating to heal at {nearest_medivac} hp {unit.health_percentage}")
            self.healing_unit_tags.add(unit.tag)
        # elif self.bot.townhalls:
        #     landed_townhalls = self.bot.townhalls.filter(lambda th: not th.is_flying)
        #     if landed_townhalls:
        #         closest_townhall = landed_townhalls.closest_to(unit)
        #     if closest_townhall and unit.distance_to(closest_townhall) > 5:
        #         unit.move(closest_townhall)
        #     else:
        #         self.attack_something(unit, 0.0)
        else:
            return False
        return True
        
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
        elif tank_to_enemy_distance < unit.distance_to(closest_enemy):
            # defend tank if it's closer to enemy than unit
            return nearest_tank
        return None

    async def move(self, unit: Unit, target: Point2, force_move: bool = False) -> None:
        if unit.tag in self.bot.unit_tags_received_action:
            return
        if self.avoid_effects(unit, force_move):
            logger.debug(f"unit {unit} avoiding effects")
        elif await self.use_ability(unit, target, health_threshold=self.ability_health, force_move=force_move):
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
        elif await self.retreat(unit, health_threshold=0.75):
            pass
        # elif self.attack_something(unit, health_threshold=0.0):
        #     pass
        elif await self.retreat(unit, health_threshold=0.5):
            pass
        else:
            logger.debug(f"scout {unit} moving to updated assignment {scouting_location}")
            unit.move(scouting_location)

    async def repair(self, unit: Unit, target: Unit):
        if unit.tag in self.bot.unit_tags_received_action:
            return
        if self.avoid_effects(unit, force_move=False):
            logger.debug(f"unit {unit} avoiding effects")
        elif self.bot.time < 360:
            unit.repair(target)
        else:
            tank_to_retreat_to = self.tank_to_retreat_to(unit)
            if tank_to_retreat_to:
                unit.move(unit.position.towards(tank_to_retreat_to.position, 2))
            elif await self.retreat(unit, health_threshold=0.25):
                logger.debug(f"unit {unit} retreating while repairing {target}")
            else:
                unit.repair(target)
