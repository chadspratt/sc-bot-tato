from __future__ import annotations
# import math
from loguru import logger

from sc2.units import Units
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2
from sc2.constants import UnitTypeId, TARGET_AIR, TARGET_GROUND
from sc2.ids.effect_id import EffectId
from sc2.ids.ability_id import AbilityId

from bottato.unit_types import UnitTypes
from bottato.map.map import Map
from bottato.mixins import GeometryMixin
from bottato.enemy import Enemy


class BaseUnitMicro(GeometryMixin):
    ability_health: float = 0.1
    attack_health: float = 0.1
    retreat_health: float = 0.75
    time_in_frames_to_attack: float = 0.25 * 22.4
    scout_tags: set[int] = set()
    healing_unit_tags: set[int] = set()
    
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
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map):
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.map: Map = map

    ###########################################################################
    # meta actions - used by non-micro classes to order units
    ###########################################################################
    async def move(self, unit: Unit, target: Point2, force_move: bool = False, previous_position: Point2 = None) -> bool:
        attack_health = self.attack_health
        if force_move and unit.distance_to_squared(target) < 225:
            # force move is used for retreating. allow attacking and other micro when near staging location
            attack_health = 0.0
            force_move = False
            
        if unit.tag in self.bot.unit_tags_received_action:
            return
        if self._avoid_effects(unit, force_move):
            pass
        elif await self._use_ability(unit, target, health_threshold=self.ability_health, force_move=force_move):
            pass
        elif self._attack_something(unit, health_threshold=attack_health, force_move=force_move):
            pass
        elif force_move:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(target)
            return True
        elif await self._retreat(unit, health_threshold=self.retreat_health):
            pass
        else:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(target)
            return True
        return False

    async def scout(self, unit: Unit, scouting_location: Point2):
        self.scout_tags.add(unit.tag)
        if unit.tag in self.bot.unit_tags_received_action:
            return
        logger.debug(f"scout {unit} health {unit.health}/{unit.health_max} ({unit.health_percentage}) health")

        if self._avoid_effects(unit, False):
            logger.debug(f"unit {unit} avoiding effects")
        elif await self._use_ability(unit, scouting_location, health_threshold=1.0):
            pass
        elif await self._retreat(unit, health_threshold=0.95):
            pass
        elif unit.type_id == UnitTypeId.VIKINGFIGHTER and self._attack_something(unit, health_threshold=1.0):
            pass
        # elif await self.retreat(unit, health_threshold=0.5):
        #     pass
        else:
            logger.debug(f"scout {unit} moving to updated assignment {scouting_location}")
            unit.move(scouting_location)

    async def repair(self, unit: Unit, target: Unit):
        if unit.tag in self.bot.unit_tags_received_action:
            return
        if self._avoid_effects(unit, force_move=False):
            logger.debug(f"unit {unit} avoiding effects")
        elif self.bot.time < 360 and target.type_id in (UnitTypeId.BARRACKS, UnitTypeId.BARRACKSREACTOR, UnitTypeId.BARRACKSTECHLAB, UnitTypeId.SUPPLYDEPOT):
            # keep ramp wall repaired early game
            unit.repair(target)
        else:
            if self._retreat_to_tank(unit, can_attack=True):
                logger.debug(f"unit {unit} retreating to tank")
            elif await self._retreat(unit, health_threshold=0.25):
                logger.debug(f"unit {unit} retreating while repairing {target}")
            elif not target.is_structure and unit.distance_to(target) > unit.radius + target.radius + 0.5:
                # sometimes they get in a weird state where they run from the target
                unit.move(target.position)
            else:
                unit.repair(target)

    ###########################################################################
    # main actions - iterated through by meta actions
    ###########################################################################
    def _avoid_effects(self, unit: Unit, force_move: bool) -> bool:
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
                if unit.position == effects_to_avoid[0]:
                    new_position = unit.position.towards(self.bot.start_location, 2)
                else:
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

    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        return False

    offensive_structure_types = (
        UnitTypeId.BUNKER,
        UnitTypeId.PHOTONCANNON,
        UnitTypeId.MISSILETURRET,
        UnitTypeId.SPINECRAWLER,
        UnitTypeId.SPORECRAWLER,
    )
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        if force_move:
            return False
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        if unit.health_percentage < health_threshold:
            return False
        candidates = []

        attackable_enemies = self.bot.enemy_units.filter(lambda u: u.can_be_attacked and u.armor < 10) + self.bot.enemy_structures.of_type(self.offensive_structure_types)
        candidates = UnitTypes.in_attack_range_of(unit, attackable_enemies, bonus_distance=3)
        if len(candidates) == 0:
            candidates = UnitTypes.in_attack_range_of(unit, self.bot.enemy_structures)

        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if unit.is_flying and can_attack and candidates:
            threats = candidates.filter(lambda u: UnitTypes.can_attack_air(u))
            if len(threats) < 4:
                if threats:
                    lowest_target = threats.sorted(key=lambda enemy_unit: enemy_unit.health + enemy_unit.shield).first
                    unit.attack(lowest_target)
                else:
                    lowest_target = candidates.sorted(key=lambda enemy_unit: enemy_unit.health + enemy_unit.shield).first
                    unit.attack(lowest_target)
                return True

        if self._retreat_to_tank(unit, can_attack):
            return True

        if not candidates:
            return False

        if can_attack:
            lowest_target = candidates.sorted(key=lambda enemy_unit: enemy_unit.health + enemy_unit.shield).first
            unit.attack(lowest_target)
            return True
        
        return self._stay_at_max_range(unit, candidates)

    async def _retreat(self, unit: Unit, health_threshold: float) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        threats = self.enemy.threats_to(unit)

        if not threats:
            if unit.type_id == UnitTypeId.SCV:
                # needs to be doing the repairing
                return False
            if unit.health_percentage >= health_threshold:
                return False
            else:
                if unit.is_mechanical:
                    repairers = self.bot.workers.filter(lambda unit: hasattr(unit, 'is_repairer')) or self.bot.workers
                    # if repairers:
                    #     repairers = repairers.filter(lambda worker: worker.tag != unit.tag)
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

        # retreat if there is nothing this unit can attack
        do_retreat = False
        if UnitTypes.can_attack(unit):
            visible_threats = threats.filter(lambda t: t.age == 0)
            targets = UnitTypes.in_attack_range_of(unit, visible_threats, bonus_distance=3)
            if not targets:
                if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
                    unit(AbilityId.UNSIEGE_UNSIEGE)
                    return True
                do_retreat = True

        # check if incoming damage will bring unit below health threshold
        if not do_retreat:
            total_potential_damage = sum([threat.calculate_damage_vs_target(unit)[0] for threat in threats])
            if not unit.health_max:
                # rare weirdness
                return True
            if (unit.health - total_potential_damage) / unit.health_max < health_threshold:
                do_retreat = True

        if do_retreat:
            avg_threat_position = threats.center
            if unit.distance_to(self.bot.start_location) < avg_threat_position.distance_to(self.bot.start_location) - 2:
                unit.move(self.bot.start_location)
                return True
            retreat_position = unit.position.towards(avg_threat_position, -5)
            # .towards(self.bot.start_location, 2)
            if self._move_to_pathable_position(unit, retreat_position):
                return True

            if unit.position == avg_threat_position:
                # avoid divide by zero
                unit.move(self.bot.start_location)
            else:
                threat_to_unit_vector = (unit.position - avg_threat_position).normalized
                tangent_vector = Point2((-threat_to_unit_vector.y, threat_to_unit_vector.x)) * unit.movement_speed
                away_from_enemy_position = unit.position.towards(avg_threat_position, -1)
                circle_around_positions = [away_from_enemy_position + tangent_vector, away_from_enemy_position - tangent_vector]
                path_to_start = self.map.get_path_points(unit.position, self.bot.start_location)
                next_waypoint = self.bot.start_location
                if len(path_to_start) > 1:
                    next_waypoint = path_to_start[1]
                circle_around_positions.sort(key=lambda pos: pos.distance_to(next_waypoint))
                unit.move(circle_around_positions[0].towards(self.bot.start_location, 2))
            return True
        return False

    ###########################################################################
    # utility behaviors - used by main actions
    ###########################################################################
    def _stay_at_max_range(self, unit: Unit, targets: Units = None) -> bool:
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
                    return self._move_to_pathable_position(unit, target_position)
                if distance_to_tank < 15:
                    attack_range = 14
                    target_position = nearest_sieged_tank.position.towards(unit, attack_range)
                    return self._move_to_pathable_position(unit, target_position)

        attack_range = UnitTypes.range_vs_target(unit, nearest_target)
        future_enemy_position = nearest_target.position
        if nearest_target.distance_to(unit) > attack_range / 2:
            future_enemy_position = self.enemy.get_predicted_position(nearest_target, unit.weapon_cooldown / 22.4)
        target_position = future_enemy_position.towards(unit, attack_range + unit.radius + nearest_target.radius)
        return self._move_to_pathable_position(unit, target_position)

    weapon_speed_vs_target_cache: dict[UnitTypeId, dict[UnitTypeId, float]] = {}

    def _kite(self, unit: Unit, target: Unit = None) -> bool:
        attack_range = UnitTypes.range_vs_target(unit, target)
        target_range = UnitTypes.range_vs_target(target, unit)
        do_kite = attack_range > target_range and unit.movement_speed >= target.movement_speed
        if do_kite:
            # can attack while staying out of range
            target_distance = self.distance(unit, target) - target.radius - unit.radius
            if target_distance < target_range + 0.8:
                if self._stay_at_max_range(unit, Units([target], bot_object=self.bot)):
                    return True
        unit.attack(target)
        return True
    
    def _move_to_pathable_position(self, unit: Unit, position: Point2) -> bool:
        if unit.is_flying and self.bot.in_map_bounds(position) or self.bot.in_pathing_grid(position):
            unit.move(position)
            return True
        return False

    def _retreat_to_medivac(self, unit: Unit) -> bool:
        medivacs = self.bot.units.filter(lambda unit: unit.type_id == UnitTypeId.MEDIVAC and unit.energy > 5 and unit.cargo_used == 0)
        if medivacs:
            nearest_medivac = medivacs.closest_to(unit)
            if unit.distance_to(nearest_medivac) > 4:
                unit.move(nearest_medivac)
            else:
                self._attack_something(unit, 0.0)
            logger.debug(f"{unit} marine retreating to heal at {nearest_medivac} hp {unit.health_percentage}")
            self.healing_unit_tags.add(unit.tag)
        else:
            return False
        return True
    
    retreat_to_tank_excluded_types: set[UnitTypeId] = set((
            UnitTypeId.PROBE,
            UnitTypeId.SCV,
            UnitTypeId.DRONE,
            UnitTypeId.DRONEBURROWED,
            UnitTypeId.MULE,
            UnitTypeId.OBSERVER,
            UnitTypeId.LARVA,
            UnitTypeId.EGG
    ))
    def _retreat_to_tank(self, unit: Unit, can_attack: bool) -> bool:
        if unit.health_percentage >= 0.9:
            # poke out at full health otherwise enemy might never be engaged
            return False
        if unit.type_id in {UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}:
            return False
        tanks = self.bot.units.of_type((UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED))
        if not tanks:
            return False

        close_enemies = self.bot.enemy_units.closer_than(15, unit).filter(
            lambda u: u.type_id not in self.retreat_to_tank_excluded_types and not u.is_flying and UnitTypes.can_attack_ground(u) and u.unit_alias != UnitTypeId.CHANGELING)
        if len(close_enemies) == 0:
            return False
        
        closest_enemy = close_enemies.closest_to(unit)
        if closest_enemy.is_flying:
            return False

        nearest_tank = tanks.closest_to(unit)
        tank_to_enemy_distance = self.distance(nearest_tank, closest_enemy)
        if tank_to_enemy_distance > 13.5 + nearest_tank.radius + closest_enemy.radius and tank_to_enemy_distance < 40:
            optimal_distance = 13.5 - UnitTypes.ground_range(closest_enemy) - unit.radius + nearest_tank.radius - 0.5
            unit.move(nearest_tank.position.towards(unit.position, optimal_distance))
            return True
        elif not can_attack and tank_to_enemy_distance < unit.distance_to(closest_enemy) + 3:
            # defend tank if it's closer to enemy than unit
            unit.move(nearest_tank.position.towards(closest_enemy.position, 3))
            return True
        return False
