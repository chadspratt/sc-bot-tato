import math
from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.data import Race

from bottato.log_helper import LogHelper
from bottato.counter import Counter
from bottato.unit_types import UnitTypes
from bottato.build_step import BuildStep
from bottato.economy.workers import Workers
from bottato.squad.squad_type import SquadType, SquadTypeDefinitions
from bottato.squad.base_squad import BaseSquad
from bottato.squad.formation_squad import FormationSquad
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.enemy import Enemy
from bottato.map.map import Map
from bottato.mixins import GeometryMixin, DebugMixin, UnitReferenceMixin, TimerMixin

class Bunker(BaseSquad):
    def __init__(self, bot: BotAI):
        super().__init__(bot=bot, name="bunker", color=(255, 255, 0))
        self.structure = None
    
    def empty(self):
        # command units to exit
        if self.structure:
            self.structure(AbilityId.UNLOADALL_BUNKER)
        self.units.clear()
    
    def pop(self):
        # command one unit to exit
        if self.units:
            unit = self.units.pop()
            # command unit to exit bunker
            return unit
        return None

    def salvage(self):
        # command to salvage the bunker
        self.structure(AbilityId.SALVAGEBUNKER_SALVAGE)

    def is_built(self):
        return self.structure is not None

    def has_space(self):
        return self.is_built() and len(self.units) < 4
    
    def update_references(self, units_by_tag):
        if self.is_built():
            try:
                self.structure = self.get_updated_unit_reference(self.structure, units_by_tag)
            except self.UnitNotFound:
                self.structure = None

class StuckRescue(BaseSquad, UnitReferenceMixin):
    def __init__(self, bot: BotAI, main_army: FormationSquad, squads_by_unit_tag: dict[int, BaseSquad]):
        super().__init__(bot=bot, name="stuck rescue", color=(255, 0, 255))
        self.main_army = main_army
        self.squads_by_unit_tag: dict[int, BaseSquad] = {}

        self.transport: Unit = None
        self.is_loaded: bool = False
        self.dropoff: Point2 = None

        self.pending_unload: set[int] = set()

    def update_references(self, units_by_tag: dict[int, Unit]):
        if self.transport:
            try:
                self.transport = self.get_updated_unit_reference(self.transport, units_by_tag)
            except self.UnitNotFound:
                self.transport = None
                self.is_loaded = False
                self.dropoff = None

    def rescue(self, stuck_units: List[Unit]):
        if self.pending_unload:
            tags_to_check = list(self.pending_unload)
            for tag in tags_to_check:
                try:
                    unit = self.get_updated_unit_reference_by_tag(tag, None)
                    self.main_army.recruit(unit)
                    self.squads_by_unit_tag[unit.tag] = self.main_army
                    self.pending_unload.remove(tag)
                except self.UnitNotFound:
                    pass
        if self.is_loaded:
            if not self.transport.passengers_tags:
                self.is_loaded = False
                self.dropoff = None
            else:
                self.dropoff = self.main_army.position.towards(self.bot.start_location, 8)
                self.transport.move(self.dropoff)
                if self.transport.distance_to(self.dropoff) < 5:
                    self.transport(AbilityId.UNLOADALLAT, self.transport)
                    for tag in self.transport.passengers_tags:
                        self.pending_unload.add(tag)
            return
        if not stuck_units:
            if self.transport:
                if self.transport.cargo_used > 0:
                    self.is_loaded = True
                else:
                    self.main_army.recruit(self.transport)
                    self.transport = None
                    self.is_loaded = False
            return
        if self.transport is None or self.transport.cargo_used == 0:
            medivacs = self.bot.units(UnitTypeId.MEDIVAC)
            if not medivacs:
                return
            medivacs_with_space = medivacs.filter(lambda unit: unit.cargo_left > 0)
            if not medivacs_with_space:
                return
            closest_medivac = medivacs_with_space.closest_to(stuck_units[0])
            if self.transport is None or self.transport != closest_medivac:
                if self.transport:
                    self.main_army.recruit(self.transport)
                    self.squads_by_unit_tag[self.transport.tag] = self.main_army
                self.transport = closest_medivac
                if self.transport.tag in self.squads_by_unit_tag and self.squads_by_unit_tag[self.transport.tag] is not None:
                    self.squads_by_unit_tag[self.transport.tag].remove(self.transport)
                    self.squads_by_unit_tag[self.transport.tag] = None

        cargo_left = self.transport.cargo_left
        for unit in stuck_units:
            if cargo_left >= unit.cargo_size:
                self.transport(AbilityId.LOAD, unit, True)
                cargo_left -= unit.cargo_size
            else:
                break
        if cargo_left == self.transport.cargo_left:
            # everything loaded (next frame)
            self.is_loaded = True

class Military(GeometryMixin, DebugMixin, UnitReferenceMixin, TimerMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, workers: Workers) -> None:
        self.bot: BotAI = bot
        self.enemy = enemy
        self.map = map
        self.workers = workers
        self.main_army = FormationSquad(
            bot=bot,
            enemy=enemy,
            map=map,
            type=SquadTypeDefinitions['none'],
            color=self.random_color(),
            name='main'
        )
        self.bunker = Bunker(self.bot)
        self.bunker2 = Bunker(self.bot)
        self.squads_by_unit_tag: dict[int, BaseSquad] = {}
        self.squads: List[BaseSquad] = []
        self.created_squad_type_counts: dict[int, int] = {}
        self.offense_start_supply = 200
        # one squad per enemy in base
        self.counters = Counter()
        self.countered_enemies: dict[int, FormationSquad] = {}
        self.army_ratio: float = 1.0
        self.status_message = ""
        self.stuck_rescue = StuckRescue(self.bot, self.main_army, self.squads_by_unit_tag)
        self.harass_squad = BaseSquad(bot=self.bot, name="harass", color=(0, 255, 255))
        self.units_by_tag: dict[int, Unit] = {}

    def add_to_main(self, unit: Unit) -> None:
        self.main_army.recruit(unit)
        self.squads_by_unit_tag[unit.tag] = self.main_army

    def transfer(self, unit: Unit, from_squad: BaseSquad, to_squad: BaseSquad) -> bool:
        if from_squad == to_squad:
            return True
        from_squad.transfer(unit, to_squad)
        self.squads_by_unit_tag[unit.tag] = to_squad

    def transfer_all(self, from_squad: BaseSquad, to_squad: BaseSquad) -> None:
        for unit in [unit for unit in from_squad.units]:
            self.transfer(unit, from_squad, to_squad)

    def rescue_stuck_units(self, stuck_units: List[Unit]):
        self.start_timer("rescue_stuck_units")
        self.stuck_rescue.rescue(stuck_units)
        self.stop_timer("rescue_stuck_units")

    async def manage_squads(self, iteration: int, blueprints: List[BuildStep],
                            newest_enemy_base: Point2 = None, rush_detected: bool = False):
        self.start_timer("manage_squads")
        self.main_army.draw_debug_box()

        self.start_timer("military enemies_in_base")
        self.start_timer("military enemies_in_base detection")
        base_structures = self.bot.structures.filter(lambda unit: unit.type_id != UnitTypeId.AUTOTURRET)
        if self.bot.enemy_race in (Race.Zerg, Race.Random):
            nydus_canals = self.bot.enemy_structures.of_type(UnitTypeId.NYDUSCANAL)
            if nydus_canals and base_structures.closest_distance_to(nydus_canals.first) < 25 and self.main_army.units:
                # put massive priority on killing nydus canals near base
                await self.main_army.move(nydus_canals.first.position)
                return
        enemies_in_base: Units = Units([], self.bot)
        enemies_in_base.extend(self.bot.enemy_units.filter(lambda unit: base_structures.closest_distance_to(unit) < 25))
        if self.main_army.staging_location:
            enemies_in_base.extend(self.bot.enemy_units.filter(lambda unit: self.main_army.staging_location.distance_to(unit) < 25))

        out_of_view_in_base = []
        for enemy in self.enemy.recent_out_of_view():
            if base_structures.closest_distance_to(self.enemy.predicted_position[enemy.tag]) <= 25:
                out_of_view_in_base.append(enemy)
        enemies_in_base.extend(out_of_view_in_base)

        logger.debug(f"enemies in base {enemies_in_base}")
        defend_with_main_army = False
        self.stop_timer("military enemies_in_base detection")

        self.start_timer("military enemies_in_base counter")
        # clear existing squads
        for enemy_tag in [tag for tag in self.countered_enemies.keys()]:
            defense_squad: FormationSquad = self.countered_enemies[enemy_tag]
            if defense_squad.units:
                self.transfer_all(defense_squad, self.main_army)
                self.squads.remove(defense_squad)
            del self.countered_enemies[enemy_tag]

        # assign squads to counter enemies that are alone or in small groups
        for enemy in enemies_in_base:
            if not self.main_army.units and enemy.type_id == UnitTypeId.PROBE:
                # cannon rush response
                self.workers.attack_enemy(enemy)
                continue
            if rush_detected and len(self.main_army.units) < 10:
                # don't send out units if getting rushed and army is small
                break
            elif defend_with_main_army:
                break
            
            if enemy.tag in self.countered_enemies:
                continue

            enemy_group = [e for e in enemies_in_base
                            if e.tag not in self.countered_enemies
                            and (enemy.tag == e.tag or self.distance(enemy, e) < 8)]

            defense_squad = FormationSquad(self.enemy, self.map, bot=self.bot, name=f"defense{len(self.countered_enemies.keys())}")

            desired_counters = self.counters.get_counter_list(Units(enemy_group, self.bot))
            for unit_type in desired_counters:
                available_units = self.main_army.units.of_type(unit_type)
                if available_units:
                    self.transfer(self.closest_unit_to_unit(enemy, available_units), self.main_army, defense_squad)
                else:
                    # a full composition was not assigned, disband the squad and defend with main army
                    self.transfer_all(defense_squad, self.main_army)
                    defend_with_main_army = True
                    break
            else:
                # a full composition was assigned
                self.squads.append(defense_squad)
                for e in enemy_group:
                    self.countered_enemies[e.tag] = defense_squad
                await defense_squad.move(self.enemy.predicted_position[enemy.tag])
                LogHelper.add_log(f"defending against {enemy_group} at {enemy.position} with {defense_squad}")
                break
        self.stop_timer("military enemies_in_base counter")
        self.stop_timer("military enemies_in_base")

        self.start_timer("military army value")
        # enemy_value = self.get_army_value(self.enemy.get_army())
        # main_army_value = self.get_army_value(self.main_army.units)
        # army_is_big_enough = main_army_value > enemy_value * 1.1 or self.bot.supply_used > 160
        # self.army_ratio = main_army_value / max(enemy_value, 1)
        self.army_ratio = self.calculate_army_ratio()
        army_is_big_enough = self.army_ratio > 1.3 or self.bot.supply_used > 160
        army_is_grouped = self.main_army.is_grouped()
        mount_offense = army_is_big_enough

        if defend_with_main_army:
            mount_offense = False
        elif self.bot.time < 300: # previously 600
            if rush_detected:
                mount_offense = False
            elif self.bot.supply_used < 45: # previously 110
                mount_offense = False
        if not mount_offense and enemies_in_base and self.army_ratio > 1.0:
            defend_with_main_army = True
        self.status_message = f"army ratio {self.army_ratio:.2f}\nbigger: {army_is_big_enough}, grouped: {army_is_grouped}\nattacking: {mount_offense}\ndefending: {defend_with_main_army}"
        self.bot.client.debug_text_screen(self.status_message, (0.01, 0.01))
        self.stop_timer("military army value")

        await self.manage_bunker(self.bunker, enemies_in_base, mount_offense)
        await self.manage_bunker(self.bunker2, enemies_in_base, mount_offense)

        if mount_offense:
            if self.offense_start_supply == 200:
                self.offense_start_supply = self.bot.supply_army
        else:
            self.offense_start_supply = 200

        self.start_timer("military move squads")
        await self.harass(newest_enemy_base)

        if self.main_army.units:
            self.main_army.draw_debug_box()
            self.start_timer("military move squads update formation")
            self.main_army.update_formation()
            self.stop_timer("military move squads update formation")
            if defend_with_main_army:
                LogHelper.add_log(f"squad {self.main_army.name} mounting defense")
                self.start_timer("military move squads defend")
                await self.main_army.move(enemies_in_base.closest_to(self.main_army.position).position)
                self.stop_timer("military move squads defend")
            elif mount_offense:
                logger.debug(f"squad {self.main_army.name} mounting offense")
                army_position = self.main_army.position
                target = None
                target_position = None
                attackable_enemies = self.enemy.enemies_in_view.filter(
                    lambda unit: unit.can_be_attacked and unit.armor < 10 and unit.tag not in self.countered_enemies)
                if attackable_enemies:
                    target = attackable_enemies
                    target_position = target.closest_to(army_position).position
                elif self.bot.enemy_structures:
                    target = self.bot.enemy_structures
                    target_position = target.closest_to(army_position).position
                else:
                    if newest_enemy_base:
                        target = newest_enemy_base
                        target_position = target.position
                    else:
                        target = self.bot.enemy_start_locations[0]
                        target_position = target
                if not army_is_grouped:
                    self.start_timer("military move squads regroup")
                    sieged_tanks = self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED)
                    army_center: Point2 = None
                    if sieged_tanks:
                        # regroup on sieged tanks so as not to abandon them
                        army_center = sieged_tanks.closest_to(target_position).position
                    else:
                        army_center = self.main_army.units.closest_to(target_position).position
                        # back off if too close to enemy
                        closest_enemy = army_center.closest(self.bot.enemy_units) if self.bot.enemy_units else None
                        closest_distance = closest_enemy.distance_to(army_center) if closest_enemy else 100
                        if closest_distance < 15:
                            path = self.map.get_path_points(army_center, self.bot.start_location)
                            i = 0
                            while i + 1 < len(path):
                                army_center = path[i + 1]
                                next_node_distance = path[i].distance_to(path[i + 1])
                                closest_distance += next_node_distance
                                if closest_distance >= 15:
                                    break
                                i += 1
                    await self.main_army.move(army_center, target_position, blueprints=blueprints)
                    self.stop_timer("military move squads regroup")
                else:
                    self.start_timer("military move squads attack")
                    if target:
                        await self.main_army.move(target_position)
                    self.stop_timer("military move squads attack")
            else:
                self.start_timer("military move squads stage")
                # generally a retreat due to being outnumbered
                logger.debug(f"squad {self.main_army} staging at {self.main_army.staging_location}")
                enemy_position = newest_enemy_base if newest_enemy_base else self.bot.enemy_start_locations[0]
                if rush_detected and len(self.main_army.units) < 16 and len(self.bot.townhalls) < 3:
                    self.main_army.staging_location = self.bot.main_base_ramp.top_center.towards(self.bot.start_location, 10)
                elif len(self.bot.townhalls) > 1:
                    closest_base = self.map.get_closest_unit_by_path(self.bot.townhalls, enemy_position)
                    if closest_base is None:
                        closest_base = self.bot.townhalls.closest_to(enemy_position)
                    second_closest_base = self.bot.townhalls.filter(
                        lambda base: base.tag != closest_base.tag).closest_to(enemy_position)
                    path = self.map.get_path_points(closest_base.position, second_closest_base.position)
                    backtrack_distance = 15
                    i = 0
                    while backtrack_distance > 0 and i + 1 < len(path):
                        next_node_distance = path[i].distance_to(path[i + 1])
                        if backtrack_distance <= next_node_distance:
                            self.main_army.staging_location = path[i].towards(path[i + 1], backtrack_distance)
                            break
                        backtrack_distance -= next_node_distance
                        i += 1
                else:
                    self.main_army.staging_location = self.bot.start_location.towards(enemy_position, 5)
                await self.main_army.move(self.main_army.staging_location, enemy_position, force_move=True, blueprints=blueprints)
                self.stop_timer("military move squads stage")
        self.stop_timer("military move squads")

        self.report()
        self.stop_timer("manage_squads")

    async def manage_bunker(self, bunker: Bunker, enemies_in_base: Units = None, mount_offense: bool = False):
        if mount_offense or not bunker.is_built():
            self.empty_bunker(bunker)
            return
        
        enemy_distance_to_bunker = 100
        enemy_distance_to_townhall = 100
        current_enemies = enemies_in_base.filter(lambda unit: unit.age == 0)
        if current_enemies:
            enemy_distance_to_bunker = current_enemies.closest_distance_to(bunker.structure)
            enemy_distance_to_townhall = current_enemies.closest_distance_to(self.bot.start_location)

        if self.bot.time > 300 or enemy_distance_to_townhall < 15:
            if enemy_distance_to_bunker > 9:
                self.empty_bunker(bunker)
                return

        for unit in bunker.units:
            try:
                unit = self.get_updated_unit_reference(unit, self.units_by_tag)
                # unit didn't enter bunker, maybe got stuck behind wall
                if unit.distance_to(bunker.structure) <= 2.5:
                    unit.smart(bunker.structure)
                else:
                    micro = MicroFactory.get_unit_micro(unit)
                    await micro.move(unit, bunker.structure.position)
            except Exception:
                pass

        for unit in self.main_army.units:
            if len(bunker.units) >= 4:
                break
            if unit.type_id == UnitTypeId.MARINE:
                enemy_distance_to_unit = current_enemies.closest_distance_to(unit) if current_enemies else 100
                marine_distance_to_bunker = unit.distance_to(bunker.structure)
                if marine_distance_to_bunker < enemy_distance_to_bunker or marine_distance_to_bunker < enemy_distance_to_unit:
                    # send unit to bunker if they won't have to move past enemies
                    self.transfer(unit, self.main_army, bunker)
                    unit.smart(bunker.structure)

    def empty_bunker(self, bunker: Bunker = None):
        for unit in bunker.units:
            self.squads_by_unit_tag[unit.tag] = self.main_army
        # self.bunker.transfer_all(self.main_army)
        bunker.empty()

    async def harass(self, newest_enemy_base: Point2 = None):
        if not self.harass_squad.units:
            # transfer a reaper from main army to harass squad
            reapers = self.main_army.units(UnitTypeId.REAPER)
            if reapers:
                self.transfer(reapers[0], self.main_army, self.harass_squad)
            else:
                return

        if not hasattr(self.harass_squad, 'arrived'):
            self.harass_squad.arrived = False
        if not hasattr(self.harass_squad, 'harass_location'):
            self.harass_squad.harass_location = self.bot.enemy_start_locations[0]
        distance_to_harass_location = self.harass_squad.units.closest_distance_to(self.harass_squad.harass_location)
        if not self.harass_squad.arrived:
            self.harass_squad.arrived = distance_to_harass_location < 15
        elif distance_to_harass_location > 15:
            self.harass_squad.arrived = False
            if self.harass_squad.harass_location == self.bot.enemy_start_locations[0] and newest_enemy_base:
                self.harass_squad.harass_location = newest_enemy_base
            else:
                self.harass_squad.harass_location = self.bot.enemy_start_locations[0]

        harass_location = self.harass_squad.harass_location

        for unit in self.harass_squad.units:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
            nearby_enemies = self.bot.enemy_units.filter(lambda u: UnitTypes.can_attack_ground(u) and u.distance_to(unit) < 15)
            threatening_structures = self.bot.enemy_structures.filter(
                lambda structure: structure.is_ready and structure.can_attack_ground
                    and structure.distance_to(unit) < structure.ground_range + 3)

            if not nearby_enemies and not threatening_structures:
                await micro.move(unit, harass_location)
                continue

            nearest_threat = None
            nearest_distance = 99999
            for threat in nearby_enemies + threatening_structures:
                distance = threat.distance_to_squared(unit) - UnitTypes.ground_range(threat) ** 2
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_threat = threat

            if UnitTypes.ground_range(nearest_threat) < UnitTypes.ground_range(unit):
                # kite enemies that we outrange
                # predicted_position = self.predict_future_unit_position(nearest_threat, 1, False)
                move_position = nearest_threat.position
                # if unit.weapon_cooldown != 0:
                #     move_position = nearest_threat.position.towards(unit, UnitTypes.ground_range(unit) - 0.5)
                self.bot.client.debug_line_out(nearest_threat, self.convert_point2_to_3(move_position), (255, 0, 0))
                self.bot.client.debug_sphere_out(self.convert_point2_to_3(move_position), 0.2, (255, 0, 0))
                await micro.move(unit, move_position)
                continue
            else:
            # elif nearest_threat.distance_to_squared(harass_location) < unit.distance_to_squared(harass_location):
                # try to circle around threats that outrange us
                threat_to_unit_vector = (unit.position - nearest_threat.position).normalized
                tangent_vector = Point2((-threat_to_unit_vector.y, threat_to_unit_vector.x)) * unit.movement_speed
                circle_around_positions = [unit.position + tangent_vector, unit.position - tangent_vector]
                circle_around_positions.sort(key=lambda pos: pos.distance_to(harass_location))
                await micro.move(unit, circle_around_positions[0])
                continue
            
            # nearby_workers = nearby_enemies.filter(
            #     lambda enemy: enemy.type_id in (UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE))
            # if nearby_workers:
            #     nearby_workers.sort(key=lambda worker: worker.shield_health_percentage)
            #     most_injured: Unit = nearby_workers[0]
            #     move_position = most_injured.position
            #     if unit.weapon_cooldown != 0:
            #         move_position = most_injured.position.towards(unit, UnitTypes.ground_range(unit) - 0.5)
            #     await micro.move(unit, move_position)
            # else:
            #     await micro.move(unit, harass_location)

    def get_squad_request(self, remaining_cap: int) -> list[UnitTypeId]:
        self.start_timer("get_squad_request")
        new_supply = 0
        new_units: list[UnitTypeId] = []
        for unit_type in new_units:
            new_supply += self.bot.calculate_supply_cost(unit_type)

        army_summary = self.count_units_by_type(self.bot.units)

        # unmatched_friendlies, unmatched_enemies = self.simulate_battle()
        unmatched_enemies = self.bot.enemy_units
        while new_supply < remaining_cap:
            squad_type: SquadType = SquadTypeDefinitions['full army']
            if unmatched_enemies:
                # type_summary = self.count_units_by_type(unmatched_enemies)
                property_summary = self.count_units_by_property(unmatched_enemies)
                # pick a squad type
                if property_summary['flying'] >= property_summary['ground']:
                    squad_type = SquadTypeDefinitions['anti air']
                else:
                    squad_type = SquadTypeDefinitions['full army']
            # elif unmatched_friendlies:
            #     # seem to be ahead,
            #     squad_type = SquadTypeDefinitions['full army']
            # else:
            #     squad_type = SquadTypeDefinitions['full army']

            for unit_type in squad_type.composition.unit_ids:
                if unit_type not in army_summary:
                    army_summary[unit_type] = 0
                if army_summary[unit_type] > 0:
                    army_summary[unit_type] -= 1
                else:
                    new_units.append(unit_type)
                    new_supply += self.bot.calculate_supply_cost(unit_type)
                    if new_supply > remaining_cap:
                        break

        logger.debug(f"new_supply: {new_supply} remaining_cap: {remaining_cap}")
        logger.debug(f"military requesting {new_units}")
        self.stop_timer("get_squad_request")
        return new_units
    
    def calculate_army_ratio(self) -> float:
        seconds_since_killed = min(60, 60 - (self.bot.time - 360) // 2)
        enemies = self.enemy.get_army(seconds_since_killed=seconds_since_killed)
        friendlies = self.main_army.units
        if not enemies:
            return 10.0
        if not friendlies:
            return 0.1

        passengers: list[Unit] = []
        for medivac in self.bot.units(UnitTypeId.MEDIVAC):
            for passenger in medivac.passengers:
                passengers.append(passenger)
        # clear to take upgrades in to account
        self.damage_by_type.clear()
        enemy_damage: float = self.calculate_total_damage(enemies, friendlies)
        friendly_damage: float = self.calculate_total_damage(friendlies, enemies, passengers)
        
        enemy_health: float = sum([unit.health + unit.shield for unit in enemies])
        friendly_health: float = sum([unit.health for unit in friendlies])

        enemy_strength: float = enemy_damage / max(friendly_health, 1)
        friendly_strength: float = friendly_damage / max(enemy_health, 1)

        return friendly_strength / max(enemy_strength, 0.0001)

    damage_by_type: dict[UnitTypeId, dict[UnitTypeId, float]] = {}
    def calculate_total_damage(self, attackers: Units, targets: Units, passengers: list[Unit] = None) -> float:
        total_damage: float = 0.0
        attacker_type_counts = self.count_units_by_type(attackers, use_common_type=False)
        target_type_counts = self.count_units_by_type(targets, use_common_type=False)
        passenger_type_counts = self.count_units_by_type(passengers) if passengers else {}
        # calculate dps vs each target type if not already cached
        for attacker in attackers:
            if attacker.type_id not in self.damage_by_type:
                self.damage_by_type[attacker.type_id] = {}
            for target in targets:
                if target.type_id not in self.damage_by_type[attacker.type_id]:
                    if UnitTypes.can_attack_target(attacker, target):
                        dps = attacker.calculate_dps_vs_target(target)
                    else:
                        dps = 0.0
                    self.damage_by_type[attacker.type_id][target.type_id] = dps

        # calculate average damage vs all target types
        total_damage = 0.0
        for attacker_type, attacker_count in attacker_type_counts.items():
            if attacker_type in passenger_type_counts:
                attacker_count += passenger_type_counts[attacker_type]
            total_damage_for_type = 0.0
            for target_type, target_count in target_type_counts.items():
                dps = self.damage_by_type[attacker_type][target_type]
                total_damage_for_type += dps * target_count
                if attacker_type in (UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED):
                    total_damage_for_type += dps * target_count # approximate splash damage
            average_damage = total_damage_for_type / len(targets)
            # add total average damage for all attackers of this type
            total_damage += average_damage * attacker_count
        return total_damage

    def simulate_battle(self):
        self.start_timer("simulate_battle")
        remaining_dps: dict[int, float] = {}
        remaining_health: dict[int, float] = {}

        unmatched_enemies: Units = self.enemy.get_enemies().filter(lambda unit: not unit.is_structure)
        unmatched_friendlies: Units = self.bot.units.copy()
        unattackable_enemies: Units = Units([], bot_object=self.bot).filter(lambda unit: not unit.armor < 10)
        unattackable_friendly_tags = unmatched_friendlies.tags

        # simulate all units attacking each other
        # do multiple passes until one side has no units left
        while unmatched_enemies and unmatched_friendlies:
            logger.debug(f"enemies: {unmatched_enemies}")
            logger.debug(f"friendlies: {unmatched_friendlies}")
            remaining_enemies: Units = unmatched_enemies.copy()
            remaining_friendlies: Units = unmatched_friendlies.copy()
            unmatched_enemies.clear()
            unmatched_friendlies.clear()
            remaining_dps.clear()
            enemy_unit: Unit
            for enemy_unit in remaining_enemies:
                if enemy_unit.is_hallucination:
                    continue
                # init enemy health
                if enemy_unit.tag not in remaining_health:
                    logger.debug(f"adding enemy with health {enemy_unit} - {enemy_unit.health}")
                    remaining_health[enemy_unit.tag] = enemy_unit.health
                elif remaining_health[enemy_unit.tag] <= 0:
                    # will be useful when doing multiple passes
                    continue
                enemy_can_be_attacked = False

                # match to friendlies that can attack them
                for friendly_unit in remaining_friendlies:
                    # init friendly health
                    if friendly_unit.tag not in remaining_health:
                        logger.debug(f"adding friendly with health {friendly_unit} - {friendly_unit.health}")
                        remaining_health[friendly_unit.tag] = friendly_unit.health
                    elif remaining_health[friendly_unit.tag] <= 0:
                        continue

                    if UnitTypes.can_attack_target(friendly_unit, enemy_unit):
                        enemy_can_be_attacked = True
                        # init friendly dps
                        if friendly_unit.tag not in remaining_dps:
                            # approximation since dps will differ by target
                            remaining_dps[friendly_unit.tag] = friendly_unit.calculate_dps_vs_target(enemy_unit)
                        if remaining_dps[friendly_unit.tag] > 0:
                            smaller_amount = min(remaining_health[enemy_unit.tag], remaining_dps[friendly_unit.tag])
                            remaining_health[enemy_unit.tag] -= smaller_amount
                            remaining_dps[friendly_unit.tag] -= smaller_amount
                            logger.debug(f"subtracting {smaller_amount} from enemy health {enemy_unit}:{remaining_health[enemy_unit.tag]} and friendly dps  - {friendly_unit}{remaining_dps[friendly_unit.tag]}")

                    if UnitTypes.can_attack_target(enemy_unit, friendly_unit):
                        if friendly_unit.tag in unattackable_friendly_tags:
                            unattackable_friendly_tags.remove(friendly_unit.tag)
                        # init enemy dps
                        if enemy_unit.tag not in remaining_dps:
                            remaining_dps[enemy_unit.tag] = enemy_unit.calculate_dps_vs_target(friendly_unit)
                        if remaining_dps[enemy_unit.tag] > 0:
                            smaller_amount = min(remaining_health[friendly_unit.tag], remaining_dps[enemy_unit.tag])
                            remaining_health[friendly_unit.tag] -= smaller_amount
                            remaining_dps[enemy_unit.tag] -= smaller_amount
                            logger.debug(f"subtracting {smaller_amount} from friendly health {friendly_unit}:{remaining_health[friendly_unit.tag]} and enemy dps  - {enemy_unit}{remaining_dps[enemy_unit.tag]}")

                    if remaining_health[enemy_unit.tag] == 0:
                        break
                else:
                    logger.debug(f"no matching friendlies for {enemy_unit}")
                    unmatched_enemies.append(enemy_unit)
                if not enemy_can_be_attacked:
                    logger.debug(f"unattackable enemy {enemy_unit}")
                    unattackable_enemies.append(enemy_unit)

            for friendly_unit in remaining_friendlies:
                if friendly_unit.tag not in remaining_health or remaining_health[friendly_unit.tag] > 0:
                    logger.debug(f"no matching enemies for {friendly_unit}")
                    unmatched_friendlies.append(friendly_unit)
            if unattackable_enemies or unattackable_friendly_tags:
                logger.debug(f"unattackables: {unattackable_enemies} {unattackable_friendly_tags}")
                # stalemate of stuff that can't attack (not considering abilities)
                break
        self.stop_timer("simulate_battle")
        return (unmatched_friendlies, unmatched_enemies)

    def report(self):
        _report = "[==MILITARY==] "
        for squad in self.squads:
            _report += squad.get_report() + ", "
        _report += self.main_army.get_report()
        logger.debug(_report)

    def update_references(self, units_by_tag: dict[int, Unit]):
        self.start_timer("update_references")
        self.units_by_tag = units_by_tag
        for unit in self.bot.units:
            if unit.tag in self.squads_by_unit_tag:
                squad = self.squads_by_unit_tag[unit.tag]
                # keep in sync
                if unit not in squad.units:
                    squad.recruit(unit)
                continue
            if unit.tag in self.bunker.units.tags:
                continue
            if unit.type_id in (UnitTypeId.SCV, UnitTypeId.MULE):
                continue
            self.add_to_main(unit)
        for squad in self.squads:
            squad.update_references(units_by_tag)
        self.main_army.update_references(units_by_tag)
        self.stuck_rescue.update_references(units_by_tag)
        self.harass_squad.update_references(units_by_tag)
        self.bunker.update_references(units_by_tag)
        self.stop_timer("update_references")

    def record_death(self, unit_tag):
        if unit_tag in self.squads_by_unit_tag:
            squad = self.squads_by_unit_tag[unit_tag]
            if squad:
                squad.remove_by_tag(unit_tag)
            del self.squads_by_unit_tag[unit_tag]
