from typing import List, Dict
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.building.build_step import BuildStep
from bottato.counter import Counter
from bottato.economy.workers import Workers
from bottato.enemy import Enemy
from bottato.enums import BuildType
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import GeometryMixin, DebugMixin, timed, timed_async
from bottato.squad.bunker import Bunker
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.formation_squad import FormationSquad
from bottato.squad.harass_squad import HarassSquad
from bottato.squad.hunting_squad import HuntingSquad
from bottato.squad.squad import Squad
from bottato.squad.stuck_rescue import StuckRescue
from bottato.unit_types import UnitTypes
from bottato.unit_reference_helper import UnitReferenceHelper


class Military(GeometryMixin, DebugMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, workers: Workers, intel: EnemyIntel) -> None:
        self.bot = bot
        self.enemy = enemy
        self.map = map
        self.workers = workers
        self.intel = intel

        self.squads: List[Squad] = []
        self.squads_by_unit_tag: Dict[int, Squad | None] = {}
        self.created_squad_type_counts: Dict[int, int] = {}
        self.offense_start_supply = 200
        self.offense_started = False
        self.army_ratio: float = 1.0
        self.status_message = ""
        self.units_by_tag: Dict[int, Unit] = {}
        self.enemies_in_base: Units = Units([], self.bot)
        self.anti_banshee_units: Units | None = None
        # special squads
        self.main_army = FormationSquad(
            bot=bot,
            enemy=enemy,
            map=map,
            color=self.random_color(),
            name='main',
        )
        self.top_ramp_bunker = Bunker(self.bot, 1)
        self.natural_bunker = Bunker(self.bot, 2)
        self.bunkers = [self.top_ramp_bunker, self.natural_bunker]
        self.stuck_rescue = StuckRescue(self.bot, self.main_army, self.squads_by_unit_tag)
        self.reaper_harass = HarassSquad(self.bot, name="reaper harass")
        self.banshee_harass = HarassSquad(self.bot, name="banshee harass")
        self.hunting_squad: HuntingSquad | None = None
        self.squads.append(self.main_army)
        self.squads.append(self.top_ramp_bunker)
        self.squads.append(self.natural_bunker)
        self.squads.append(self.stuck_rescue)
        self.squads.append(self.reaper_harass)
        self.squads.append(self.banshee_harass)

    def add_to_main(self, unit: Unit) -> None:
        self.main_army.recruit(unit)
        self.squads_by_unit_tag[unit.tag] = self.main_army

    def transfer(self, unit: Unit, from_squad: Squad, to_squad: Squad) -> None:
        if from_squad != to_squad:
            from_squad.transfer(unit, to_squad)
            self.squads_by_unit_tag[unit.tag] = to_squad
            if to_squad not in self.squads:
                self.squads.append(to_squad)

    def transfer_all(self, from_squad: Squad, to_squad: Squad) -> None:
        for unit in [unit for unit in from_squad.units]:
            self.transfer(unit, from_squad, to_squad)

    def rescue_stuck_units(self, stuck_units: List[Unit]):
        self.stuck_rescue.rescue(stuck_units)

    @timed_async
    async def manage_squads(self, iteration: int,
                            blueprints: List[BuildStep],
                            newest_enemy_base: Point2 | None,
                            detected_enemy_builds: Dict[BuildType, float],
                            proxy_buildings: Units):
        self.main_army.draw_debug_box()

        await self.harass(detected_enemy_builds)
        await self.manage_special_squads()

        self.enemies_in_base = await self.get_enemies_in_base()
        if self.enemies_in_base(UnitTypeId.NYDUSCANAL):
            return  # nydus response handled in get_enemies_in_base, don't conflict with it
        defend_with_main_army, countered_enemies = await self.counter_enemies_in_base(detected_enemy_builds)
        
        self.army_ratio = self.calculate_army_ratio()
        enemies_in_base_ratio = self.calculate_army_ratio(self.enemies_in_base)

        army_is_big_enough = self.army_ratio > 1.3 or self.bot.supply_used > 160 or self.offense_started and self.army_ratio > 0.9
        army_is_grouped = self.main_army.is_grouped()
        mount_offense = army_is_big_enough and not defend_with_main_army

        if not self.enemies_in_base and proxy_buildings:
            # if proxy buildings detected, mount offense even if army is small
            mount_offense = True
        elif mount_offense: # previously 600
            if self.bot.units([UnitTypeId.REAPER, UnitTypeId.VIKINGFIGHTER]).amount == 0 and self.bot.time < 420:
                # wait for a scout to attack
                mount_offense = False
            elif len(detected_enemy_builds) > 0 and self.bot.time < 360:
                mount_offense = False
            elif self.bot.supply_used < 50: # previously 110
                mount_offense = False
        if not mount_offense and self.enemies_in_base and self.army_ratio > 1.0:
            defend_with_main_army = True

        self.offense_started = mount_offense

        self.status_message = f"army ratio {self.army_ratio:.2f}\nbigger: {army_is_big_enough}, grouped: {army_is_grouped}\nattacking: {mount_offense}\ndefending: {defend_with_main_army}"
        self.bot.client.debug_text_screen(self.status_message, (0.01, 0.01))
        closest_bunker_to_center: Bunker | None = None
        closest_bunker_to_center_distance: float = float('inf')
        for bunker in self.bunkers:
            if not bunker.structure:
                continue
            distance_to_map_center = bunker.structure.distance_to_squared(self.bot.game_info.map_center) if bunker.structure else float('inf')
            if bunker.structure and distance_to_map_center < closest_bunker_to_center_distance:
                closest_bunker_to_center = bunker
                closest_bunker_to_center_distance = distance_to_map_center
        for bunker in self.bunkers:
            if mount_offense or not bunker.structure:
                self.empty_bunker(bunker)
            else:
                is_closest = bunker == closest_bunker_to_center
                await self.manage_bunker(bunker, self.enemies_in_base, is_closest)

        if self.main_army.units:
            self.main_army.draw_debug_box()
            self.main_army.update_formation()
            if defend_with_main_army and (self.bot.time > 420 or enemies_in_base_ratio >= 1.0):
                LogHelper.add_log(f"squad {self.main_army.name} mounting defense")
                await self.main_army.move(self.enemies_in_base.closest_to(self.main_army.position).position)
            elif mount_offense and len(proxy_buildings) > 0 and self.bot.time < 420:
                target_position = proxy_buildings.closest_to(self.main_army.position).position
                await self.main_army.move(target_position)
            elif mount_offense:
                LogHelper.add_log(f"squad {self.main_army.name} mounting offense")
                target_position: Point2 | None = self.get_offense_target_position(newest_enemy_base, countered_enemies)
                if not army_is_grouped:
                    await self.regroup(target_position, blueprints)
                else:
                    if target_position:
                        await self.main_army.move(target_position) # slow, 50%+ of command time
            else:
                await self.move_army_to_staging_location(newest_enemy_base, detected_enemy_builds, blueprints)

    @timed_async
    async def get_enemies_in_base(self) -> Units:
        enemies_in_base = Units([], self.bot)
        base_structures = self.bot.structures.filter(lambda unit: unit.type_id != UnitTypeId.AUTOTURRET)
        if self.bot.enemy_race in (Race.Zerg, Race.Random):
            nydus_canals = self.bot.enemy_structures.of_type(UnitTypeId.NYDUSCANAL)
            if nydus_canals and self.closest_distance_squared(nydus_canals.first, base_structures) < 625 and self.main_army.units:
                LogHelper.add_log(f"attacking nydus canals in base: {nydus_canals}")
                # put massive priority on killing nydus canals near base
                if self.main_army.position._distance_squared(nydus_canals.first.position) > 225:
                    await self.main_army.move(nydus_canals.first.position, force_move=True)
                else:
                    await self.main_army.move(nydus_canals.first.position)
                return nydus_canals
        
        enemy_units = self.bot.enemy_units
        if self.main_army.units.amount < 3:
            enemy_units = enemy_units.exclude_type([UnitTypeId.OVERLORD])

        enemies_in_base.extend(enemy_units.filter(lambda unit: self.closest_distance_squared(unit, base_structures) < 625))
        if self.main_army.staging_location:
            enemies_in_base.extend(enemy_units.filter(lambda unit: self.main_army.staging_location._distance_squared(unit.position) < 625))
        out_of_view_in_base = []
        for enemy in self.enemy.recent_out_of_view():
            if self.closest_distance_squared(self.enemy.predicted_position[enemy.tag], base_structures) < 625:
                out_of_view_in_base.append(enemy)
        enemies_in_base.extend(out_of_view_in_base)

        logger.debug(f"enemies in base {enemies_in_base}")
        return enemies_in_base
    
    @timed_async
    async def counter_enemies_in_base(self, detected_enemy_builds: Dict[BuildType, float]) -> tuple[bool, Dict[int, FormationSquad]]:
        defend_with_main_army = False
        countered_enemies: Dict[int, FormationSquad] = {}
        # clear existing defense squads
        for squad in list(self.squads):
            if squad.name.startswith("defense"):
                self.transfer_all(squad, self.main_army)
                self.squads.remove(squad)

        defense_squad_count = 0

        # assign squads to counter enemies that are alone or in small groups
        for enemy in self.enemies_in_base:
            if not self.main_army.units and enemy.type_id == UnitTypeId.PROBE:
                # cannon rush response
                self.workers.attack_enemy(enemy)
                continue
            if len(detected_enemy_builds) > 0 and len(self.main_army.units) < 10:
                # don't send out units if getting rushed and army is small
                defend_with_main_army = True
                break
            elif defend_with_main_army:
                break
            
            if enemy.tag in countered_enemies:
                continue

            enemy_group = [e for e in self.enemies_in_base
                            if e.tag not in countered_enemies
                            and (enemy.tag == e.tag or self.distance(enemy, e, self.enemy.predicted_position) < 8)]
            overlords_excluded = [e for e in enemy_group if e.type_id not in (UnitTypeId.OVERLORD, UnitTypeId.OVERSEER)]

            defense_squad = FormationSquad(self.bot, self.enemy, self.map, name=f"defense{defense_squad_count}")
            defense_squad_count += 1

            desired_counters = Counter.get_counter_list(Units(enemy_group, self.bot))
            if not desired_counters:
                continue
            for unit_type in desired_counters:
                available_units = self.main_army.units.of_type(unit_type).filter(lambda u: u.health_percentage > 0.4)
                if available_units:
                    self.transfer(self.closest_unit_to_unit(enemy, available_units), self.main_army, defense_squad)
                else:
                    # a full composition was not assigned, disband the squad and defend with main army
                    self.transfer_all(defense_squad, self.main_army)
                    if len(overlords_excluded) > 0:
                        # respond to overlords but don't dedicate entire army
                        defend_with_main_army = True
                    break
            else:
                # a full composition was assigned

                for e in enemy_group:
                    countered_enemies[e.tag] = defense_squad
                await defense_squad.move(self.enemy.predicted_position[enemy.tag])
                LogHelper.add_log(f"defending against {enemy_group} at {enemy.position} with {defense_squad}")
                break
        return defend_with_main_army, countered_enemies

    @timed_async
    async def manage_bunker(self, bunker: Bunker, enemies_in_base: Units, is_closest_to_enemy: bool = False):
        if not bunker.structure:
            return
        for passenger in bunker.structure.passengers:
            if passenger.type_id == UnitTypeId.SCV:
                # SCV accidentally entered bunker, remove them
                self.empty_bunker(bunker)
                break
        
        current_enemies = enemies_in_base.filter(lambda unit: unit.age == 0)
        closest_enemy: Unit | None = None
        enemy_distance_to_bunker = 10000
        if current_enemies:
            closest_enemy = self.closest_unit_to_unit(bunker.structure, current_enemies)
            enemy_distance_to_bunker = closest_enemy.distance_to_squared(bunker.structure)

        if not is_closest_to_enemy:
            if not closest_enemy:
                self.empty_bunker(bunker)
                return

            enemy_distance_to_main = self.closest_distance_squared(self.bot.start_location, current_enemies) if current_enemies else 10000
            buffer = 2 if enemy_distance_to_main > 300 else 0

            bunker_range = self.enemy.get_attack_range_with_buffer(bunker.structure, closest_enemy, buffer)
            if bunker_range < enemy_distance_to_bunker < 10000:
                self.empty_bunker(bunker, closest_enemy)
                return

        # add units to bunker
        for unit in bunker.units:
            try:
                unit = UnitReferenceHelper.get_updated_unit_reference(unit)
                # unit didn't enter bunker, maybe got stuck behind wall
                if unit.distance_to_squared(bunker.structure) <= 20:
                    unit.smart(bunker.structure)
                else:
                    micro = MicroFactory.get_unit_micro(unit)
                    await micro.move(unit, bunker.structure.position, force_move=True)
            except Exception:
                pass

        cargo_max = bunker.structure.cargo_max
        cargo_used = sum(u.cargo_size for u in bunker.units)
        if cargo_used < cargo_max:
            for squad in self.squads:
                if squad == self.main_army or squad.name.startswith("defense"):
                    valid_units = squad.units.of_type({UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.GHOST})
                    closest_units = valid_units.closest_n_units(bunker.structure, cargo_max - cargo_used)
                    for unit in closest_units:
                        enemy_distance_to_unit = self.closest_distance_squared(unit, current_enemies) if current_enemies else 10000
                        marine_distance_to_bunker = unit.distance_to_squared(bunker.structure)
                        if marine_distance_to_bunker < enemy_distance_to_bunker or marine_distance_to_bunker < enemy_distance_to_unit:
                            # send unit to bunker if they won't have to move past enemies
                            self.transfer(unit, self.main_army, bunker)
                            unit.smart(bunker.structure)
                            cargo_used += unit.cargo_size
                            if cargo_used >= cargo_max:
                                return

    def empty_bunker(self, bunker: Bunker, destination: Unit | None = None):
        for unit in bunker.units:
            self.squads_by_unit_tag[unit.tag] = self.main_army
        # self.bunker.transfer_all(self.main_army)
        bunker.empty(destination)

    @timed_async
    async def harass(self, detected_enemy_builds: Dict[BuildType, float]):
        if BuildType.PROXY in detected_enemy_builds and self.bot.enemy_units(UnitTypeId.REAPER) and self.bot.time < 300:
            # stop harass during proxy reaper rush
            self.transfer_all(self.reaper_harass, self.main_army)
        elif not self.reaper_harass.units:
            # transfer a reaper from main army to harass squad
            reapers = self.main_army.units(UnitTypeId.REAPER)
            if reapers:
                self.transfer(reapers[0], self.main_army, self.reaper_harass)

        if self.banshee_harass.units.amount < 2 and (self.bot.enemy_race != Race.Terran or len(detected_enemy_builds) > 0):
            if not self.anti_banshee_units:
                self.anti_banshee_units = self.bot.enemy_units((UnitTypeId.VIKINGFIGHTER, UnitTypeId.PHOENIX, UnitTypeId.MUTALISK))
            if not self.anti_banshee_units:
                # transfer a banshee from main army to harass squad
                banshees = self.main_army.units(UnitTypeId.BANSHEE)
                if banshees:
                    self.transfer(banshees[0], self.main_army, self.banshee_harass)
            
        await self.reaper_harass.harass(self.intel)
        await self.banshee_harass.harass(self.intel)

    @timed_async
    async def manage_special_squads(self):
        hunter_types: List[UnitTypeId] = []
        prey_types: List[UnitTypeId] = []
        if self.intel.enemy_race_confirmed == Race.Zerg:
            hunter_types = [UnitTypeId.VIKINGFIGHTER, UnitTypeId.VIKINGASSAULT]
            prey_types = [UnitTypeId.OVERLORD, UnitTypeId.OVERSEER]
        elif self.intel.enemy_race_confirmed == Race.Terran:
            hunter_types = [UnitTypeId.VIKINGFIGHTER, UnitTypeId.VIKINGASSAULT]
            prey_types = [UnitTypeId.MEDIVAC]
        if hunter_types:
            if self.hunting_squad is None:
                self.hunting_squad = HuntingSquad(self.bot, self.enemy, self.intel, f"{prey_types[0].name} hunt", (255, 0, 255))
                LogHelper.add_log(f"created hunting squad {self.hunting_squad.name}")
                self.squads.append(self.hunting_squad)
            if not self.hunting_squad.units:
                hunters = self.main_army.units(hunter_types)
                if hunters:
                    self.transfer(hunters.first, self.main_army, self.hunting_squad)
            if self.hunting_squad.units:
                await self.hunting_squad.hunt(prey_types)

    @timed
    def get_offense_target_position(self, newest_enemy_base: Point2 | None, countered_enemies: Dict[int, FormationSquad]) -> Point2:
        army_position = self.main_army.position
        target_position: Point2
        attackable_enemies = self.enemy.enemies_in_view.filter(
            lambda unit: not unit.is_structure
                and UnitTypes.can_be_attacked(unit, self.bot, self.enemy.get_enemies())
                and unit.armor < 10
                and unit.tag not in countered_enemies)
        
        ignored_enemy_tags = set()
        closest_structure = self.bot.enemy_structures.closest_to(army_position) if self.bot.enemy_structures else None
        closest_structure_distance = closest_structure.distance_to_squared(army_position) if closest_structure else 100000
        enemy_army: Units | None = None
        enemy_army_distance: float = 100000

        for enemy in attackable_enemies:
            enemy_distance = self.distance_squared(enemy, army_position)
            if enemy.tag in ignored_enemy_tags or enemy_distance > closest_structure_distance:
                continue
            enemy_group = attackable_enemies.filter(lambda e: e.tag not in ignored_enemy_tags
                            and self.distance_squared(enemy, e, self.enemy.predicted_position) < 64)
            if len(enemy_group) >= 3:
                enemy_army = enemy_group
                enemy_army_distance = enemy_distance
                break
            for e in enemy_group:
                ignored_enemy_tags.add(e.tag)

        if enemy_army and enemy_army_distance < closest_structure_distance:
            target_position = enemy_army.center
        elif closest_structure:
            target_position = closest_structure.position
        elif newest_enemy_base:
            target_position = newest_enemy_base
        else:
            target_position = self.bot.enemy_start_locations[0]
        return target_position
    
    @timed_async
    async def move_army_to_staging_location(self, newest_enemy_base: Point2 | None, detected_enemy_builds: Dict[BuildType, float], blueprints: List[BuildStep]):
        # generally a retreat due to being outnumbered
        LogHelper.add_log(f"squad {self.main_army} staging at {self.main_army.staging_location}")
        enemy_position = newest_enemy_base if newest_enemy_base else self.bot.enemy_start_locations[0]
        if len(detected_enemy_builds) > 0 and len(self.bot.townhalls) < 3 and len(self.main_army.units) < 16:
            ramp_depots = self.bot.structures(UnitTypeId.SUPPLYDEPOT).filter(lambda depot: depot.position.manhattan_distance(self.bot.main_base_ramp.top_center) < 5)
            if len(ramp_depots) >= 2:
                # depots are raised, crowd around ramp to defend
                self.main_army.staging_location = self.bot.main_base_ramp.top_center
            else:
                self.main_army.staging_location = self.bot.main_base_ramp.top_center.towards(self.bot.start_location, 5)
        elif len(detected_enemy_builds) > 0 and len(self.bot.townhalls) <= 3 and self.army_ratio < 1.0:
            self.main_army.staging_location = self.map.natural_position.towards(self.bot.main_base_ramp.bottom_center, 5)
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
        # force move is used for retreating. don't use if already near staging location
        force_move = self.main_army.position._distance_squared(self.main_army.staging_location) >= 225
        await self.main_army.move(self.main_army.staging_location, enemy_position, force_move=force_move, blueprints=blueprints)

    @timed_async
    async def regroup(self, target_position: Point2, blueprints: List[BuildStep]):
        LogHelper.add_log(f"main_army regrouping")
        sieged_tanks = self.bot.units.of_type(UnitTypeId.SIEGETANKSIEGED).filter(lambda u: u.distance_to_squared(self.main_army.position) < 225)
        army_center: Point2
        if sieged_tanks:
            # regroup on sieged tanks so as not to abandon them
            army_center = sieged_tanks.closest_to(target_position).position
        else:
            army_center = self.main_army.units.closest_to(target_position).position
            # back off if too close to enemy
            closest_enemy = army_center.closest(self.bot.enemy_units) if self.bot.enemy_units else None
            remaining_distance = 15 - closest_enemy.distance_to(army_center) if closest_enemy else 0
            if remaining_distance > 0:
                path = self.map.get_path_points(army_center, self.bot.start_location)
                i = 0
                while i + 1 < len(path):
                    army_center = path[i + 1]
                    next_node_distance = path[i].distance_to(path[i + 1])
                    remaining_distance -= next_node_distance
                    if remaining_distance < 0:
                        army_center = path[i + 1].towards(path[i], -remaining_distance)
                        break
                    i += 1
        await self.main_army.move(army_center, target_position, blueprints=blueprints)
    
    passenger_stand_ins: Dict[UnitTypeId, Unit] = {}
    damage_by_type_cache_friendly: Dict[UnitTypeId, Dict[UnitTypeId, float]] = {}
    damage_by_type_cache_enemy: Dict[UnitTypeId, Dict[UnitTypeId, float]] = {}
    damage_by_type_cache_timestamp: float = 0.0
    # XXX why does this fluctuate
    @timed
    def calculate_army_ratio(self, enemies_in_base: Units | None = None) -> float:
        # update in case new upgrades have finished
        if self.bot.time - self.damage_by_type_cache_timestamp > 20:
            self.damage_by_type_cache_friendly.clear()
            self.damage_by_type_cache_enemy.clear()
            self.damage_by_type_cache_timestamp = self.bot.time

        # account for rebuilt units earlier in game when they make up a bigger portion
        enemies = enemies_in_base
        if enemies is None:
            seconds_since_killed = min(60, 60 - (self.bot.time - 300) // 2)
            enemies = self.enemy.get_army(seconds_since_killed=seconds_since_killed).filter(lambda unit: not unit.is_structure)
        friendlies = self.main_army.units.copy()
        for friendly in friendlies + self.top_ramp_bunker.units + self.natural_bunker.units:
            if hasattr(friendly, "build_progress"):
                self.passenger_stand_ins[friendly.type_id] = friendly
        medivacs = friendlies.of_type(UnitTypeId.MEDIVAC)
        for medivac in medivacs:
            if medivac.passengers:
                for passenger in medivac.passengers:
                    friendlies.append(passenger)
        for bunker in self.bunkers:
            if bunker.structure and bunker.structure.passengers:
                for passenger in bunker.structure.passengers:
                    friendlies.append(passenger)
                    
        if not enemies:
            return 10.0
        if not friendlies:
            return 0.1

        friendly_damage: float = self.calculate_total_damage(friendlies, enemies, self.damage_by_type_cache_friendly)
        enemy_damage: float = self.calculate_total_damage(enemies, friendlies, self.damage_by_type_cache_enemy)
        
        friendly_health: float = sum([unit.health for unit in friendlies])
        enemy_health: float = sum([unit.health + unit.shield for unit in enemies])
        for carrier in friendlies.of_type([UnitTypeId.BUNKER, UnitTypeId.MEDIVAC]):
            for passenger in carrier.passengers:
                friendly_health += passenger.health

        enemy_strength: float = enemy_damage / max(friendly_health, 1)
        friendly_strength: float = friendly_damage / max(enemy_health, 1)

        return friendly_strength / max(enemy_strength, 0.0001)

    @timed
    def calculate_total_damage(self, attackers: Units, targets: Units, damage_by_type_cache: Dict[UnitTypeId, Dict[UnitTypeId, float]]) -> float:
        attackers_by_type = UnitTypes.group_units_by_type(attackers, use_common_type=False)
        targets_by_type = UnitTypes.group_units_by_type(targets, use_common_type=False)
        self.calculate_damage_by_type(attackers_by_type, targets_by_type, damage_by_type_cache)

        total_damage: float = 0.0

        # calculate average damage vs all target types
        for attacker_type, attacker_list in attackers_by_type.items():
            total_damage_for_type = 0.0
            total_count = 0
            for target_type, target_list in targets_by_type.items():
                if target_type not in damage_by_type_cache[attacker_type]:
                    logger.warning(f"missing dps for {attacker_type} vs {target_type}")
                    logger.warning(f"damage_by_type_cache: {damage_by_type_cache}")
                dps = damage_by_type_cache[attacker_type][target_type]
                total_damage_for_type += dps * len(target_list)
                total_count += len(target_list) 
                if attacker_type in (UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED):
                    total_damage_for_type += dps * len(target_list) # approximate splash damage
            average_damage = total_damage_for_type / total_count if total_count > 0 else 0.0
            # add total average damage for all attackers of this type
            total_damage += average_damage * len(attacker_list)
        return total_damage
    
    @timed
    def calculate_damage_by_type(self, attackers: Dict[UnitTypeId, List[Unit]], targets: Dict[UnitTypeId, List[Unit]], damage_by_type_cache: Dict[UnitTypeId, Dict[UnitTypeId, float]]):
        # calculate dps vs each target type if not already cached
        for attacker_type, attacker_list in attackers.items():
            if attacker_type not in damage_by_type_cache:
                damage_by_type_cache[attacker_type] = {}
            for target_type, target_list in targets.items():
                if target_type not in damage_by_type_cache[attacker_type]:
                    attacker = next((attacker for attacker in attacker_list if hasattr(attacker, 'build_progress')), attacker_list[0])
                    target = next((target for target in target_list if hasattr(target, 'build_progress')), target_list[0])
                    # passengers always have base_build -1, use stand-in unit for calculations
                    if not hasattr(attacker, 'build_progress'):
                        try:
                            attacker = self.passenger_stand_ins[attacker_type]
                        except KeyError:
                            logger.warning(f"missing stand-in for passenger attacker type {attacker_type}")
                            logger.warning(f" stand-ins {self.passenger_stand_ins}")
                            damage_by_type_cache[attacker_type][target_type] = 5.0
                            continue
                    if not hasattr(target, 'build_progress'):
                        try:
                            target = self.passenger_stand_ins[target_type]
                        except KeyError:
                            logger.warning(f"missing stand-in for passenger target type {target_type}")
                            damage_by_type_cache[attacker_type][target_type] = 5.0
                            continue
                    dps = UnitTypes.dps(attacker, target)
                    damage_by_type_cache[attacker_type][target_type] = dps
    
    def get_non_passenger_from_list(self, unit_list: List[Unit]) -> Unit | None:
        for unit in unit_list:
            if hasattr(unit, "build_progress"):
                return unit
        return None

    @timed
    def simulate_battle(self):
        remaining_dps: Dict[int, float] = {}
        remaining_health: Dict[int, float] = {}

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
        return (unmatched_friendlies, unmatched_enemies)

    @timed
    def update_references(self):
        self.squads_by_unit_tag.clear()
        for squad in self.squads:
            squad.update_references()
            for unit in squad.units:
                self.squads_by_unit_tag[unit.tag] = squad
        for unit in self.bot.units:
            if unit.tag not in self.squads_by_unit_tag and unit.type_id not in (UnitTypeId.SCV, UnitTypeId.MULE):
                self.add_to_main(unit)

    def record_death(self, unit_tag):
        if unit_tag in self.squads_by_unit_tag:
            squad = self.squads_by_unit_tag[unit_tag]
            if squad:
                squad.remove_by_tag(unit_tag)
            del self.squads_by_unit_tag[unit_tag]
        for bunker in self.bunkers:
            if bunker.structure and bunker.structure.tag == unit_tag:
                bunker.empty()
                bunker.structure = None
