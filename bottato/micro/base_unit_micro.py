from __future__ import annotations
from typing import Dict
# import math
from loguru import logger

from sc2.units import Units
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.position import Point2
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId

from bottato.log_helper import LogHelper
from bottato.unit_types import UnitTypes
from bottato.map.map import Map
from bottato.mixins import GeometryMixin, TimerMixin
from bottato.enemy import Enemy


class BaseUnitMicro(GeometryMixin, TimerMixin):
    ability_health: float = 0.1
    attack_health: float = 0.1
    retreat_health: float = 0.75
    time_in_frames_to_attack: float = 0.25 * 22.4
    scout_tags: set[int] = set()
    harass_tags: set[int] = set()
    healing_unit_tags: set[int] = set()
    tanks_being_retreated_to: Dict[int, float] = {}
    tanks_being_retreated_to_prev_frame: Dict[int, float] = {}
    harass_location_reached_tags: set[int] = set()
    repair_started_tags: set[int] = set()
    repairer_tags: set[int] = set()
    repairer_tags_prev_frame: set[int] = set()

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

    @staticmethod
    def reset_tag_sets():
        BaseUnitMicro.tanks_being_retreated_to_prev_frame = BaseUnitMicro.tanks_being_retreated_to
        BaseUnitMicro.tanks_being_retreated_to = {}
        BaseUnitMicro.repairer_tags_prev_frame = BaseUnitMicro.repairer_tags
        BaseUnitMicro.repairer_tags = set()

    ###########################################################################
    # meta actions - used by non-micro classes to order units
    ###########################################################################
    async def move_to_repairer(self, unit: Unit, target: Point2, force_move: bool = False, previous_position: Point2 | None = None) -> bool:
        if unit.tag not in BaseUnitMicro.repair_started_tags and unit.position.manhattan_distance(target) < 2.0:
            LogHelper.add_log(f"move_to_repairer {unit} is close to worker")
            BaseUnitMicro.repair_started_tags.add(unit.tag)
        if unit.tag in BaseUnitMicro.scout_tags:
            await self.scout(unit, target)
            return True
        elif unit.tag in BaseUnitMicro.harass_tags:
            return await self.harass(unit, target, force_move=force_move, previous_position=previous_position)
        else:
            return await self.move(unit, target, force_move=force_move, previous_position=previous_position)

    async def move(self, unit: Unit, target: Point2, force_move: bool = False, previous_position: Point2 | None = None) -> bool:
        if unit.tag in BaseUnitMicro.scout_tags:
            BaseUnitMicro.scout_tags.remove(unit.tag)
        elif unit.tag in BaseUnitMicro.harass_tags:
            BaseUnitMicro.harass_tags.remove(unit.tag)
        attack_health = self.attack_health
        # if force_move and unit.distance_to_squared(target) < 144:
        #     # force move is used for retreating. allow attacking and other micro when near staging location
        #     attack_health = 0.0
        #     force_move = False
            
        if unit.tag in self.bot.unit_tags_received_action:
            return True
        self.start_timer("base_unit_micro.move._avoid_effects")
        action_taken = self._avoid_effects(unit, force_move)
        self.stop_timer("base_unit_micro.move._avoid_effects")
        if not action_taken:
            self.start_timer("base_unit_micro.move._use_ability")
            action_taken = await self._use_ability(unit, target, health_threshold=self.ability_health, force_move=force_move)
            self.stop_timer("base_unit_micro.move._use_ability")
        if not action_taken:
            self.start_timer("base_unit_micro.move._attack_something")
            action_taken = self._attack_something(unit, health_threshold=attack_health, force_move=force_move)
            self.stop_timer("base_unit_micro.move._attack_something")
        if not action_taken and force_move:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(target)
            action_taken = True
        if not action_taken:
            self.start_timer("base_unit_micro.move._retreat")
            action_taken = await self._retreat(unit, health_threshold=self.retreat_health)
            self.stop_timer("base_unit_micro.move._retreat")
        
        if not action_taken:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(target)
        return True

    async def harass(self, unit: Unit, target: Point2, force_move: bool = False, previous_position: Point2 | None = None) -> bool:
        BaseUnitMicro.harass_tags.add(unit.tag)
        if unit.tag not in BaseUnitMicro.harass_location_reached_tags:
            if unit.position.manhattan_distance(target) < 10:
                BaseUnitMicro.harass_location_reached_tags.add(unit.tag)
        attack_health = self.attack_health
        # if force_move and unit.distance_to_squared(target) < 144:
        #     # force move is used for retreating. allow attacking and other micro when near staging location
        #     attack_health = 0.0
        #     force_move = False
            
        if unit.tag in self.bot.unit_tags_received_action:
            LogHelper.add_log(f"harass {unit} already has action")
            return True
        self.start_timer("base_unit_micro.move._avoid_effects")
        action_taken = self._avoid_effects(unit, force_move)
        self.stop_timer("base_unit_micro.move._avoid_effects")
        if not action_taken:
            self.start_timer("base_unit_micro.move._use_ability")
            action_taken = await self._use_ability(unit, target, health_threshold=self.ability_health, force_move=force_move)
            self.stop_timer("base_unit_micro.move._use_ability")
        if not action_taken:
            self.start_timer("base_unit_micro.move._attack_something")
            action_taken = self._harass_attack_something(unit, health_threshold=attack_health, force_move=force_move)
            self.stop_timer("base_unit_micro.move._attack_something")
        if not action_taken and force_move:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(target)
            action_taken = True
        if not action_taken:
            self.start_timer("base_unit_micro.move._retreat")
            action_taken = await self._harass_retreat(unit, health_threshold=self.retreat_health)
            self.stop_timer("base_unit_micro.move._retreat")
        
        if not action_taken:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(target)
        return True

    async def scout(self, unit: Unit, scouting_location: Point2):
        BaseUnitMicro.scout_tags.add(unit.tag)
        if unit.tag in self.bot.unit_tags_received_action:
            return
        logger.debug(f"scout {unit} health {unit.health}/{unit.health_max} ({unit.health_percentage}) health")

        if self._avoid_effects(unit, False):
            logger.debug(f"unit {unit} avoiding effects")
        # elif await self._use_ability(unit, scouting_location, health_threshold=1.0):
        #     pass
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
        BaseUnitMicro.repairer_tags.add(unit.tag)
        if unit.tag in self.bot.unit_tags_received_action:
            return
        if self._avoid_effects(unit, force_move=False):
            logger.debug(f"unit {unit} avoiding effects")
        elif target.type_id in (UnitTypeId.BUNKER, UnitTypeId.PLANETARYFORTRESS):
            # repair defensive structures regardless of risk
            unit.repair(target)
        elif self.bot.time < 360 and target.distance_to_squared(self.bot.main_base_ramp.top_center) < 9:
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
            safe_distance = (effect.radius + unit.radius + 1.5) ** 2
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
                unit.move(new_position) # type: ignore
                return True
            average_x = sum(p.x for p in effects_to_avoid) / number_of_effects
            average_y = sum(p.y for p in effects_to_avoid) / number_of_effects
            average_position = Point2((average_x, average_y))
            # move out of effect radius
            new_position = unit.position.towards(average_position, -2)
            unit.move(new_position) # type: ignore
            return True
        return False

    last_targets_update_time: float = 0.0
    valid_targets: Units | None = None
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        return False

    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False

        if self.last_targets_update_time != self.bot.time:
            self.last_targets_update_time = self.bot.time
            self.valid_targets = self.bot.enemy_units.filter(
                lambda u: u.can_be_attacked and u.armor < 10 and BuffId.NEURALPARASITE not in u.buffs
                ).sorted(key=lambda u: u.health + u.shield) + self.bot.enemy_structures

        if not self.valid_targets:
            return False
        nearby_enemies = self.valid_targets.closer_than(20, unit)
        if not nearby_enemies:
            return False
        
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if can_attack:
            bonus_distance = -2 if unit.health_percentage < health_threshold else 0
            # attack enemy in range
            attack_target = self._get_attack_target(unit, nearby_enemies, bonus_distance)
            if attack_target:
                self._attack(unit, attack_target)
                return True
        
        # don't attack if low health and there are threats
        if unit.health_percentage < health_threshold:
            if self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6):
                return False
            
        # no enemy in range, stay near tanks
        if self._retreat_to_tank(unit, can_attack):
            return True
            
        # venture out to attack further enemy
        if can_attack:
            attack_target = self._get_attack_target(unit, nearby_enemies, 5)
            if attack_target:
                unit.attack(attack_target)
                return True
        elif self.valid_targets:
            return self._stay_at_max_range(unit, self.valid_targets)

        # if force_move:
        #     return False

        return False
    
    def _harass_attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        return self._attack_something(unit, health_threshold, force_move)

    async def _retreat(self, unit: Unit, health_threshold: float) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=4)

        if not threats:
            if unit.health_percentage >= health_threshold:
                return False
        else:
            if not unit.health_max:
                # rare weirdness
                return True
            # check if incoming damage will bring unit below health threshold
            total_potential_damage = sum([threat.calculate_damage_vs_target(unit)[0] for threat in threats])
            if (unit.health - total_potential_damage) / unit.health_max >= health_threshold:
                return False

        if unit.type_id == UnitTypeId.SCV and not threats and not unit.is_constructing_scv:
            injured_units = self.bot.units.filter(lambda u: u.health_percentage < 1.0 and u.tag != unit.tag and u.is_mechanical and u.type_id != UnitTypeId.MULE)
            if injured_units:
                unit.repair(injured_units.closest_to(unit))
                return True

        # retreat if there is nothing this unit can attack and it's not an SCV which might be repairing
        if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
            visible_threats = threats.filter(lambda t: t.age == 0)
            targets = self.enemy.in_attack_range(unit, visible_threats, 3)
            if not targets:
                unit(AbilityId.UNSIEGE_UNSIEGE)
                return True

        retreat_position = self._get_retreat_destination(unit, threats)
        unit.move(retreat_position)
        return True
    
    async def _harass_retreat(self, unit: Unit, health_threshold: float) -> bool:
        return await self._retreat(unit, health_threshold)

    ###########################################################################
    # utility behaviors - used by main actions
    ###########################################################################
    def _get_attack_target(self, unit: Unit, nearby_enemies: Units, bonus_distance: float = 0) -> Unit | None:
        priority_targets = nearby_enemies.filter(lambda u: u.type_id in UnitTypes.HIGH_PRIORITY_TARGETS)
        if priority_targets:
            in_range = self.enemy.in_attack_range(unit, priority_targets, bonus_distance)
            if in_range:
                return in_range.sorted(lambda u: u.health + u.shield).first
        offensive_targets = nearby_enemies.filter(lambda u: UnitTypes.can_attack(u))
        if offensive_targets:
            threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=0)
            if threats:
                in_range = self.enemy.in_attack_range(unit, threats, bonus_distance)
                if in_range:
                    return in_range.sorted(lambda u: u.health + u.shield).first
            in_range = self.enemy.in_attack_range(unit, offensive_targets, bonus_distance)
            if in_range:
                return in_range.sorted(lambda u: u.health + u.shield).first
        passive_targets = nearby_enemies.filter(lambda u: not UnitTypes.can_attack(u))
        if passive_targets:
            in_range = self.enemy.in_attack_range(unit, passive_targets, bonus_distance)
            if in_range:
                return in_range.sorted(lambda u: u.health + u.shield).first
            
    def _stay_at_max_range(self, unit: Unit, targets: Units) -> bool:
        if not targets:
            return False
        nearest_target = self.closest_unit_to_unit(unit, targets)
        # don't keep distance from structures since it prevents units in back from attacking
        # except for zerg structures that spawn broodlings when they die
        if nearest_target.is_structure and (nearest_target.race != "Zerg" or nearest_target.type_id not in UnitTypes.ZERG_STRUCTURES_THAT_DONT_SPAWN_BROODLINGS):
            unit.move(nearest_target.position)
            return True
        # move away if weapon on cooldown
        if not unit.is_flying:
            nearest_sieged_tank = None
            if nearest_target.type_id == UnitTypeId.SIEGETANKSIEGED:
                nearest_sieged_tank = nearest_target
            else:
                enemy_tanks = targets.of_type(UnitTypeId.SIEGETANKSIEGED)
                if enemy_tanks:
                    nearest_sieged_tank = self.closest_unit_to_unit(unit, enemy_tanks)

            if nearest_sieged_tank:
                distance_to_tank = self.distance(unit, nearest_sieged_tank)
                if distance_to_tank < 7:
                    # dive on sieged tanks
                    attack_range = 0
                    target_position = nearest_sieged_tank.position.towards(unit, attack_range)
                    return self._move_to_pathable_position(unit, target_position) # type: ignore
                if distance_to_tank < 15:
                    attack_range = 14
                    target_position = nearest_sieged_tank.position.towards(unit, attack_range)
                    return self._move_to_pathable_position(unit, target_position) # type: ignore

        attack_range = UnitTypes.range_vs_target(unit, nearest_target)
        future_enemy_position = nearest_target.position
        # if nearest_target.distance_to(unit) > attack_range / 2:
        #     future_enemy_position = self.enemy.get_predicted_position(nearest_target, unit.weapon_cooldown / 22.4)
        target_position = future_enemy_position.towards(unit, attack_range + unit.radius + nearest_target.radius - 1)
        return self._move_to_pathable_position(unit, target_position) # type: ignore

    weapon_speed_vs_target_cache: dict[UnitTypeId, dict[UnitTypeId, float]] = {}

    def _kite(self, unit: Unit, target: Unit) -> bool:
        attack_range = UnitTypes.range_vs_target(unit, target)
        target_range = UnitTypes.range_vs_target(target, unit)
        do_kite = attack_range > target_range and unit.movement_speed > target.movement_speed
        if do_kite:
            # can attack while staying out of range
            target_distance = self.distance(unit, target) - target.radius - unit.radius
            if target_distance < attack_range - 0.8:
                if self._stay_at_max_range(unit, Units([target], bot_object=self.bot)):
                    return True
                unit.move(self._get_retreat_destination(unit, Units([target], bot_object=self.bot)))
                return True
        self._attack(unit, target)
        return True
    
    def _attack(self, unit: Unit, target: Unit) -> bool:
        if target.type_id == UnitTypeId.INTERCEPTOR:
            # interceptors can't be targeted directly
            unit.attack(target.position)
        elif target.age > 0:
            unit.move(self.enemy.predicted_position[target.tag])
        else:
            unit.attack(target)
        return True
    
    def _move_to_pathable_position(self, unit: Unit, position: Point2) -> bool:
        if unit.is_flying and self.bot.in_map_bounds(position) or self.bot.in_pathing_grid(position):
            unit.move(position)
            return True
        return False
            
    def _get_retreat_destination(self, unit: Unit, threats: Units) -> Point2:
        ultimate_destination: Point2 | None = None
        if unit.is_mechanical:
            if not threats:
                repairers: Units = self.bot.workers.filter(lambda w: w.tag in BaseUnitMicro.repairer_tags_prev_frame) or self.bot.workers
                # if repairers:
                #     repairers = repairers.filter(lambda worker: worker.tag != unit.tag)
                if repairers:
                    closest_repairer = repairers.closest_to(unit)
                    ultimate_destination = closest_repairer.position
        else:
            medivacs = self.bot.units.of_type(UnitTypeId.MEDIVAC)
            if medivacs:
                ultimate_destination = medivacs.closest_to(unit).position
        if ultimate_destination is None:
            bunkers = self.bot.structures.of_type(UnitTypeId.BUNKER)
            if bunkers:
                ultimate_destination = bunkers.closest_to(unit).position.towards(unit, -2) # type: ignore
        
        if not ultimate_destination:
            ultimate_destination = self.bot.game_info.player_start_location
        
        if not threats:
            return ultimate_destination

        avg_threat_position = threats.center
        if unit.distance_to(ultimate_destination) < avg_threat_position.distance_to(ultimate_destination) - 2:
            return ultimate_destination
        retreat_distance = -10 if unit.is_flying else -5
        retreat_position = unit.position.towards(avg_threat_position, retreat_distance)
        # .towards(ultimate_destination, 2)
        if self._position_is_pathable(unit, retreat_position): # type: ignore
            return retreat_position # type: ignore

        if unit.position == avg_threat_position:
            # avoid divide by zero
            return ultimate_destination
        else:
            circle_around_position = self.get_circle_around_position(unit, avg_threat_position, ultimate_destination)
            return circle_around_position.towards(ultimate_destination, 2) # type: ignore
    
    def _position_is_pathable(self, unit: Unit, position: Point2) -> bool:
        if unit.is_flying and self.bot.in_map_bounds(position) or self.bot.in_pathing_grid(position):
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
        self.start_timer("_retreat_to_tank")
        if unit.type_id in {UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}:
            self.stop_timer("_retreat_to_tank")
            return False
        if not unit.can_be_attacked:
            self.stop_timer("_retreat_to_tank")
            return False
        tanks = self.bot.units.of_type((UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED))
        if not tanks:
            self.stop_timer("_retreat_to_tank")
            return False
        if unit.health_percentage >= 0.9:
            nearby_injured_friendlies = self.bot.units.filter(lambda u: u.health_percentage < 0.9 and u.type_id in (UnitTypeId.MARINE, UnitTypeId.MARAUDER)).closer_than(5, unit)
            # poke out at full health otherwise enemy might never be engaged
            if not nearby_injured_friendlies:
                return False
            #     tank_to_enemy_distance += 3.0

        close_enemies = self.bot.enemy_units.closer_than(15, unit).filter(
            lambda u: u.type_id not in self.retreat_to_tank_excluded_types and not u.is_flying and UnitTypes.can_attack_ground(u) and u.unit_alias != UnitTypeId.CHANGELING)
        if len(close_enemies) == 0:
            self.stop_timer("_retreat_to_tank")
            return False
        
        closest_enemy = close_enemies.closest_to(unit)
        if closest_enemy.is_flying:
            self.stop_timer("_retreat_to_tank")
            return False

        nearest_tank = tanks.closest_to(unit)
        tank_to_enemy_distance = self.distance(nearest_tank, closest_enemy)
        if tank_to_enemy_distance > 13.5 + nearest_tank.radius + closest_enemy.radius and tank_to_enemy_distance < 40:
            optimal_distance = 13.5 - UnitTypes.ground_range(closest_enemy) - unit.radius + nearest_tank.radius - 2.0
            unit.move(nearest_tank.position.towards(unit.position, optimal_distance)) # type: ignore
            if nearest_tank.tag not in BaseUnitMicro.tanks_being_retreated_to or tank_to_enemy_distance < BaseUnitMicro.tanks_being_retreated_to[nearest_tank.tag]:
                BaseUnitMicro.tanks_being_retreated_to[nearest_tank.tag] = tank_to_enemy_distance
            self.stop_timer("_retreat_to_tank")
            return True
        elif not can_attack and tank_to_enemy_distance < unit.distance_to(closest_enemy) + 3:
            # defend tank if it's closer to enemy than unit
            unit.move(nearest_tank.position.towards(closest_enemy.position, 3)) # type: ignore
            if nearest_tank.tag not in BaseUnitMicro.tanks_being_retreated_to or tank_to_enemy_distance < BaseUnitMicro.tanks_being_retreated_to[nearest_tank.tag]:
                BaseUnitMicro.tanks_being_retreated_to[nearest_tank.tag] = tank_to_enemy_distance
            self.stop_timer("_retreat_to_tank")
            return True
        self.stop_timer("_retreat_to_tank")
        return False
    
    def get_circle_around_position(self, unit: Unit, threat_position: Point2, destination: Point2) -> Point2:
        if unit.distance_to_squared(destination) > 225:
            path_to_destination = self.map.get_path_points(unit.position, destination)
            if len(path_to_destination) > 1:
                destination = path_to_destination[1]
                if unit.distance_to_squared(destination) < threat_position._distance_squared(destination):
                    return destination
        threat_to_unit_vector = (unit.position - threat_position).normalized
        tangent_vector1 = Point2((-threat_to_unit_vector.y, threat_to_unit_vector.x)) * unit.movement_speed
        tangent_vector2 = Point2((-tangent_vector1.x, -tangent_vector1.y))
        # away_from_enemy_position = unit.position.towards(threat_position, -1)
        circle_around_positions = [Point2(unit.position + tangent_vector1),
                                    Point2(unit.position + tangent_vector2)]
        circle_around_positions.sort(key=lambda pos: pos.distance_to(destination))
        return circle_around_positions[0].towards(threat_position, -1) # type: ignore
