from __future__ import annotations
from typing import Dict, List, Tuple
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

from bottato.enemy import Enemy
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.micro.custom_effect import CustomEffect
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.unit_types import UnitTypes


class BaseUnitMicro(GeometryMixin):
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
    custom_effects_to_avoid: List[CustomEffect] = []  # position, time, radius, duration

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
    @timed_async
    async def move_to_repairer(self, unit: Unit, target: Point2, force_move: bool = True, previous_position: Point2 | None = None) -> bool:
        if unit.tag in BaseUnitMicro.repair_started_tags:
            # already being repaired
            target = unit.position
        elif unit.tag not in BaseUnitMicro.repair_started_tags and unit.position.manhattan_distance(target) < 2.0 and self.bot.in_pathing_grid(unit.position):
            LogHelper.add_log(f"move_to_repairer {unit} is close to worker")
            BaseUnitMicro.repair_started_tags.add(unit.tag)
        if unit.health_percentage > self.retreat_health and self.unit_is_closer_than(unit, self.bot.enemy_units, 15, self.bot):
            # don't move to repairer if in combat and healthy
            return False
        if unit.tag in BaseUnitMicro.scout_tags:
            await self.scout(unit, target)
            return True
        elif unit.tag in BaseUnitMicro.harass_tags:
            return await self.harass(unit, target, force_move=force_move, previous_position=previous_position)
        else:
            return await self.move(unit, target, force_move=force_move, previous_position=previous_position)

    @timed_async
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
        action_taken = self._avoid_effects(unit, force_move)
        if not action_taken:
            action_taken = await self._use_ability(unit, target, health_threshold=self.ability_health, force_move=force_move)
        if not action_taken:
            action_taken = self._attack_something(unit, health_threshold=attack_health, force_move=force_move)
        if not action_taken and force_move:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(self.map.get_pathable_position(target, unit))
            action_taken = True
        if not action_taken:
            action_taken = await self._retreat(unit, health_threshold=self.retreat_health)
        
        if not action_taken:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(self.map.get_pathable_position(target, unit))
        return True

    @timed_async
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
        action_taken = self._avoid_effects(unit, force_move)
        if not action_taken:
            action_taken = await self._use_ability(unit, target, health_threshold=self.ability_health, force_move=force_move)
        if not action_taken:
            action_taken = self._harass_attack_something(unit, attack_health, target, force_move=force_move)
        if not action_taken and force_move:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(self.map.get_pathable_position(target, unit))
            action_taken = True
        if not action_taken:
            action_taken = await self._harass_retreat(unit, health_threshold=self.retreat_health, harass_location=target)
        
        if not action_taken:
            position_to_compare = target if unit.is_moving else unit.position
            if previous_position is None or position_to_compare.manhattan_distance(previous_position) > 1:
                unit.move(self.map.get_pathable_position(target, unit))
        return True

    @timed_async
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
            unit.move(self.map.get_pathable_position(scouting_location, unit))

    @timed_async
    async def repair(self, unit: Unit, target: Unit) -> bool:
        BaseUnitMicro.repairer_tags.add(unit.tag)
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        if self._avoid_effects(unit, force_move=False):
            logger.debug(f"unit {unit} avoiding effects")
        elif target.type_id in (UnitTypeId.BUNKER, UnitTypeId.PLANETARYFORTRESS, UnitTypeId.MISSILETURRET, UnitTypeId.SIEGETANKSIEGED):
            # repair defensive structures regardless of risk
            unit.repair(target)
            return True
        elif self.bot.time < 360 and target.distance_to_squared(self.bot.main_base_ramp.top_center) < 9:
            # keep ramp wall repaired early game
            unit.repair(target)
            return True
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
                return True
        return False

    ###########################################################################
    # main actions - iterated through by meta actions
    ###########################################################################
    fixed_radius: Dict[EffectId | str, float] = {
        EffectId.PSISTORMPERSISTENT: 2,
        EffectId.GUARDIANSHIELDPERSISTENT: 4.5,
        EffectId.SCANNERSWEEP: 13,
    }
    @staticmethod
    def add_custom_effect(position: Unit | Point2, radius: float, start_time: float, duration: float):
        BaseUnitMicro.custom_effects_to_avoid.append(CustomEffect(position, radius, start_time, duration))

    @timed
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
            effect_radius = self.fixed_radius.get(effect.id, effect.radius)
            safe_distance = (effect_radius + unit.radius + 1.5) ** 2
            for position in effect.positions:
                if unit.position._distance_squared(position) < safe_distance:
                    effects_to_avoid.append(position)
        i = len(self.custom_effects_to_avoid) - 1
        while i >= 0:
            effect = self.custom_effects_to_avoid[i]
            effect_position = effect.position.position
            if self.bot.time - effect.start_time > effect.duration:
                self.custom_effects_to_avoid.pop(i)
            else:
                safe_distance = (effect.radius + unit.radius + 1.5) ** 2
                if unit.position._distance_squared(effect_position) < safe_distance:
                    effects_to_avoid.append(effect_position)
            i -= 1
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

    last_targets_update_time: float = 0.0
    valid_targets: Units | None = None
    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        return False

    @timed
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False, move_position: Point2 | None = None) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False

        if self.last_targets_update_time != self.bot.time:
            self.last_targets_update_time = self.bot.time
            self.valid_targets = self.bot.enemy_units.filter(
                lambda u: UnitTypes.can_be_attacked(u, self.bot, self.enemy.get_enemies()) and u.armor < 10 and BuffId.NEURALPARASITE not in u.buffs
                ) + self.bot.enemy_structures

        if not self.valid_targets:
            return False
        nearby_enemies = self.valid_targets.closer_than(20, unit).sorted(lambda u: u.health + u.shield)
        if not nearby_enemies:
            return False
        
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if can_attack:
            bonus_distance = -2 if unit.health_percentage < health_threshold else -0.5
            if UnitTypes.range(unit) < 1:
                bonus_distance = 1
            # attack enemy in range
            attack_target = self._get_attack_target(unit, nearby_enemies, bonus_distance)
            if attack_target:
                self._attack(unit, attack_target)
                return True
        
        # don't attack if low health and there are threats
        if unit.health_percentage < health_threshold:
            if self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6, first_only=True):
                return False
            
        # no enemy in range, stay near tanks
        if self._retreat_to_tank(unit, can_attack):
            return True
            
        if can_attack:
            # venture out to attack further enemy but don't chase too far
            if move_position and move_position.manhattan_distance(unit.position) < 20:
                attack_target = self._get_attack_target(unit, nearby_enemies, 5)
                if attack_target:
                    unit.attack(attack_target)
                    return True
        elif self.valid_targets:
            return self._stay_at_max_range(unit, self.valid_targets)

        return False
    
    @timed
    def _harass_attack_something(self, unit: Unit, health_threshold: float, harass_location: Point2, force_move: bool = False) -> bool:
        return self._attack_something(unit, health_threshold, force_move, harass_location)

    @timed_async
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
            hp_threshold = unit.health_max * health_threshold
            current_health = unit.health
            for threat in threats:
                current_health -= threat.calculate_damage_vs_target(unit)[0]
                if current_health < hp_threshold:
                    break
            else:
                return False

        if unit.type_id == UnitTypeId.SCV and not threats and not unit.is_constructing_scv:
            injured_units = self.bot.units.filter(lambda u: u.health_percentage < 1.0 and u.tag != unit.tag and u.is_mechanical and u.type_id != UnitTypeId.MULE)
            if injured_units:
                unit.repair(injured_units.closest_to(unit))
                return True

        # retreat if there is nothing this unit can attack and it's not an SCV which might be repairing
        if unit.type_id == UnitTypeId.SIEGETANKSIEGED:
            visible_threats = threats.filter(lambda t: t.age == 0)
            targets = self.enemy.in_attack_range(unit, visible_threats, 3, first_only=True)
            if not targets:
                unit(AbilityId.UNSIEGE_UNSIEGE)
                return True

        retreat_position = self._get_retreat_destination(unit, threats)
        unit.move(retreat_position)
        return True
    
    @timed_async
    async def _harass_retreat(self, unit: Unit, health_threshold: float, harass_location: Point2) -> bool:
        return await self._retreat(unit, health_threshold)

    ###########################################################################
    # utility behaviors - used by main actions
    ###########################################################################
    @timed
    def _get_attack_target(self, unit: Unit, nearby_enemies: Units, bonus_distance: float = 0) -> Unit | None:
        priority_targets = nearby_enemies.filter(lambda u: u.type_id in UnitTypes.HIGH_PRIORITY_TARGETS)
        if priority_targets:
            in_range = self.enemy.in_attack_range(unit, priority_targets, bonus_distance, first_only=True)
            if in_range:
                return in_range.first
        offensive_targets = nearby_enemies.filter(lambda u: UnitTypes.can_attack(u))
        if offensive_targets:
            threat_in_range = self.enemy.threat_in_attack_range(unit, offensive_targets, bonus_distance, first_only=True)
            if threat_in_range:
                return threat_in_range.first
            in_range = self.enemy.in_attack_range(unit, offensive_targets, bonus_distance, first_only=True)
            if in_range:
                return in_range.first
        passive_targets = nearby_enemies.filter(lambda u: not UnitTypes.can_attack(u))
        if passive_targets:
            in_range = self.enemy.in_attack_range(unit, passive_targets, bonus_distance, first_only=True)
            if in_range:
                return in_range.first
            
    def _stay_at_max_range(self, unit: Unit, targets: Units, buffer: float = 0.5) -> bool:
        if not targets:
            return False
        nearest_target = self.closest_unit_to_unit(unit, targets)
        # don't keep distance from structures since it prevents units in back from attacking
        # except for zerg structures that spawn broodlings when they die
        if nearest_target.is_structure and nearest_target.type_id not in UnitTypes.OFFENSIVE_STRUCTURE_TYPES and (nearest_target.race != "Zerg" or nearest_target.type_id not in UnitTypes.ZERG_STRUCTURES_THAT_DONT_SPAWN_BROODLINGS):
            unit.move(self.map.get_pathable_position(nearest_target.position, unit))
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
                    return self._move_to_pathable_position(unit, target_position)
                if distance_to_tank < 15:
                    attack_range = 14
                    target_position = nearest_sieged_tank.position.towards(unit, attack_range)
                    return self._move_to_pathable_position(unit, target_position)

        attack_range = UnitTypes.range_vs_target(unit, nearest_target)
        future_enemy_position = nearest_target.position
        target_position = future_enemy_position.towards(unit, attack_range + unit.radius + nearest_target.radius + buffer)
        return self._move_to_pathable_position(unit, target_position)

    weapon_speed_vs_target_cache: dict[UnitTypeId, dict[UnitTypeId, float]] = {}

    def _kite(self, unit: Unit, target: Unit) -> bool:
        attack_range = UnitTypes.range_vs_target(unit, target)
        target_range = UnitTypes.range_vs_target(target, unit)
        do_kite = UnitTypes.can_be_attacked(unit, self.bot, self.bot.enemy_units) \
            and attack_range > target_range > 0 and unit.movement_speed > target.movement_speed
        if do_kite:
            # can attack while staying out of range
            target_distance = self.distance(unit, target) - target.radius - unit.radius
            if target_distance < attack_range - 1.0:
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
            unit.move(self.map.get_pathable_position(self.enemy.predicted_position[target.tag], unit))
        else:
            unit.attack(target)
        return True
    
    def _move_to_pathable_position(self, unit: Unit, position: Point2) -> bool:
        if unit.is_flying and self.bot.in_map_bounds(position) or self.bot.in_pathing_grid(position):
            unit.move(self.map.get_pathable_position(position, unit))
            return True
        return False
            
    @timed
    def _get_retreat_destination(self, unit: Unit, threats: Units) -> Point2:
        ultimate_destination: Point2 | None = None
        if unit.is_mechanical:
            if not threats.filter(lambda t: t.can_attack):
                repairers: Units = self.bot.workers.filter(lambda w: w.tag in BaseUnitMicro.repairer_tags.union(BaseUnitMicro.repairer_tags_prev_frame)) or self.bot.workers
                if repairers:
                    repairers = repairers.filter(lambda worker: worker.tag != unit.tag)
                if repairers:
                    closest_repairer = repairers.closest_to(unit)
                    if closest_repairer.position.manhattan_distance(unit.position) < 1:
                        ultimate_destination = unit.position
                    else:
                        ultimate_destination = closest_repairer.position
        else:
            medivacs = self.bot.units.of_type(UnitTypeId.MEDIVAC)
            if medivacs:
                ultimate_destination = medivacs.closest_to(unit).position
        if ultimate_destination is None:
            bunkers = self.bot.structures.of_type(UnitTypeId.BUNKER)
            if bunkers:
                away_from_position = threats.center if threats else self.bot.game_info.map_center
                ultimate_destination = bunkers.closest_to(unit).position.towards(away_from_position, -4)
        
        if not ultimate_destination:
            ultimate_destination = self.bot.game_info.player_start_location
        
        if not threats:
            return self.map.get_pathable_position(ultimate_destination, unit)

        avg_threat_position = threats.center
        if unit.distance_to(ultimate_destination) < avg_threat_position.distance_to(ultimate_destination) - 2:
            return self.map.get_pathable_position(ultimate_destination, unit)
        retreat_distance = -10 if unit.is_flying else -5
        retreat_position = unit.position.towards(avg_threat_position, retreat_distance)
        # .towards(ultimate_destination, 2)
        if self._position_is_pathable(unit, retreat_position):
            return self.map.get_pathable_position(retreat_position, unit)

        if unit.position == avg_threat_position:
            # avoid divide by zero
            return self.map.get_pathable_position(ultimate_destination, unit)
        else:
            circle_around_position = self.get_circle_around_position(unit, avg_threat_position, ultimate_destination)
            return circle_around_position
    
    def _position_is_pathable(self, unit: Unit, position: Point2) -> bool:
        if unit.is_flying and self.bot.in_map_bounds(position) or self.bot.in_pathing_grid(position):
            return True
        return False

    @timed
    def _retreat_to_medivac(self, unit: Unit) -> bool:
        medivacs = self.bot.units.filter(lambda unit: unit.type_id == UnitTypeId.MEDIVAC and unit.energy > 5 and unit.cargo_used == 0)
        if medivacs:
            nearest_medivac = medivacs.closest_to(unit)
            if unit.distance_to_squared(nearest_medivac) > 16:
                unit.move(nearest_medivac)
            else:
                unit.move(self._get_retreat_destination(unit,self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=4)))
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
    @timed
    def _retreat_to_tank(self, unit: Unit, can_attack: bool) -> bool:
        if unit.type_id in {UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED}:
            return False
        if not UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies()):
            return False
        tanks = self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED)
        if not tanks:
            tanks = self.bot.units.of_type(UnitTypeId.SIEGETANK)
        if not tanks:
            return False
        if unit.health_percentage >= 0.9:
            injured_friendlies = self.bot.units.filter(lambda u: u.health_percentage < 0.9 and u.type_id in (UnitTypeId.MARINE, UnitTypeId.MARAUDER))
            # poke out at full health otherwise enemy might never be engaged
            if not self.unit_is_closer_than(unit, injured_friendlies, 5, self.bot):
                return False

        tank_targets = self.bot.enemy_units.filter(
            lambda u: u.type_id not in UnitTypes.NON_THREATS
                and not u.is_flying
                and UnitTypes.can_attack_ground(u)
                and u.unit_alias != UnitTypeId.CHANGELING
            )
        if not tank_targets:
            return False
        closest_enemy = tank_targets.closest_to(unit)
        if closest_enemy.distance_to_squared(unit) > 225:
            return False

        nearest_tank = tanks.closest_to(unit)
        tank_to_enemy_distance_sq = self.distance_squared(nearest_tank, closest_enemy)
        if tank_to_enemy_distance_sq < 900 and tank_to_enemy_distance_sq > (13.5 + nearest_tank.radius + closest_enemy.radius)**2:
            optimal_distance = 13.5 - UnitTypes.ground_range(closest_enemy) - unit.radius + nearest_tank.radius - 2.0
            unit.move(nearest_tank.position.towards(unit.position, optimal_distance))
            if nearest_tank.tag not in BaseUnitMicro.tanks_being_retreated_to or tank_to_enemy_distance_sq < BaseUnitMicro.tanks_being_retreated_to[nearest_tank.tag]:
                BaseUnitMicro.tanks_being_retreated_to[nearest_tank.tag] = tank_to_enemy_distance_sq
            return True
        elif not can_attack and tank_to_enemy_distance_sq < unit.distance_to_squared(closest_enemy) * 0.3:
            # defend tank if it's closer to enemy than unit
            unit.move(nearest_tank.position.towards(closest_enemy.position, 3))
            if nearest_tank.tag not in BaseUnitMicro.tanks_being_retreated_to or tank_to_enemy_distance_sq < BaseUnitMicro.tanks_being_retreated_to[nearest_tank.tag]:
                BaseUnitMicro.tanks_being_retreated_to[nearest_tank.tag] = tank_to_enemy_distance_sq
            return True
        return False
    
    @timed
    def get_circle_around_position(self, unit: Unit, threat_position: Point2, destination: Point2) -> Point2:
        if not unit.is_flying and unit.distance_to_squared(destination) > 225:
            path_to_destination = self.map.get_path_points(unit.position, destination)
            if len(path_to_destination) > 1:
                for path_position in path_to_destination:
                    distance_squared = unit.distance_to_squared(path_position)
                    if distance_squared > threat_position._distance_squared(path_position):
                        break
                    if distance_squared > 400 or path_position == path_to_destination[-1]:
                        # if no enemies along path, go to first node
                        return path_to_destination[1]
        threat_to_unit_vector = (unit.position - threat_position).normalized
        tangent_vector1 = Point2((-threat_to_unit_vector.y, threat_to_unit_vector.x)) * unit.movement_speed
        tangent_vector2 = Point2((-tangent_vector1.x, -tangent_vector1.y))
        # away_from_enemy_position = unit.position.towards(threat_position, -1)
        circle_around_positions = [Point2(unit.position + tangent_vector1),
                                    Point2(unit.position + tangent_vector2)]
        circle_around_positions.sort(key=lambda pos: pos._distance_squared(destination))
        circle_around_position = circle_around_positions[0].towards(threat_position, -1)
        return self.map.get_pathable_position(circle_around_position, unit)
