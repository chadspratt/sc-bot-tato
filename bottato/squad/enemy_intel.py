from typing import Dict, List, Tuple

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.data import race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.enemy import Enemy
from bottato.enums import BuildType, ExpansionSelection
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.mixins import GeometryMixin
from bottato.squad.scouting_location import ScoutingLocation
from bottato.unit_reference_helper import UnitReferenceHelper

class EnemyIntel(GeometryMixin):
    def __init__(self, bot: BotAI, map: Map, enemy: Enemy):
        self.bot = bot
        self.map = map
        self.enemy = enemy

        self.initial_scout_completed: bool = False
        self.enemy_main_scouted: bool = False
        self.type_positions_seen: Dict[UnitTypeId, List[Point2]] = {}
        self.first_building_time: Dict[UnitTypeId, float] = {}
        self.enemy_race_confirmed: Race | None = None
        self.enemy_builds_detected: Dict[BuildType, float] = {}
        self.proxy_buildings: Units = Units([], self.bot)
        self.enemy_drop_transports: Units = Units([], self.bot)
        self.enemy_drop_locations: List[Tuple[Point2, float]] = []

        self.scouting_locations: List[ScoutingLocation] = list()
        for expansion_location in self.bot.expansion_locations_list:
            self.scouting_locations.append(ScoutingLocation(expansion_location, expansion_location.towards(self.bot.game_info.map_center, -5)))
        self.enemy_base_built_times: Dict[Point2, float] = {self.bot.enemy_start_locations[0]: 0.0}

    def mark_initial_scout_complete(self):
        self.initial_scout_completed = True
    def mark_enemy_main_scouted(self):
        self.enemy_main_scouted = True

    async def update(self):
        self.catalog_visible_units()
        self.update_proxy_buildings()
        await self.detect_enemy_builds()
        self.update_enemy_drop_locations()

    def catalog_visible_units(self):
        """Catalog all visible enemy units and buildings"""
        # Count buildings by type
        for unit in self.bot.enemy_structures + self.bot.enemy_units:
            self.add_type(unit, self.bot.time)
        
        # Detect race if not already confirmed
        if not self.enemy_race_confirmed:
            if self.bot.enemy_race != Race.Random:
                self.enemy_race_confirmed = self.bot.enemy_race
            elif self.bot.enemy_structures:
                first_enemy: Unit = self.bot.all_enemy_units[0]
                self.enemy_race_confirmed = first_enemy.race

    def add_type(self, unit: Unit, time: float):
        if unit.type_id not in self.type_positions_seen:
            self.type_positions_seen[unit.type_id] = [unit.position]
            LogHelper.add_log(f"EnemyIntel: first seen {unit.type_id} at time {time:.1f}")
        elif unit.is_structure and unit.position not in self.type_positions_seen[unit.type_id]:
            # store position for every structure
            self.type_positions_seen[unit.type_id].append(unit.position)

        if unit.type_id not in self.first_building_time:
            start_time = time - unit.build_progress * unit._type_data.cost.time / 22.4 # type: ignore
            self.first_building_time[unit.type_id] = start_time
            LogHelper.add_log(f"EnemyIntel: first {unit.type_id} started at time {start_time:.1f}")

    def update_location_visibility(self, scout_units: List[Unit]):
        enemy_townhalls = self.bot.enemy_structures.of_type(race_townhalls[self.bot.enemy_race])

        # add new townhalls to known enemy bases
        for townhall in enemy_townhalls:
            if townhall.position not in self.enemy_base_built_times:
                self.enemy_base_built_times[townhall.position] = self.bot.time
                self.newest_enemy_base = townhall.position

        for location in self.scouting_locations:
            if self.bot.is_visible(location.scouting_position):
                location.last_seen = self.bot.time

            for townhall in enemy_townhalls:
                if location.expansion_position.manhattan_distance(townhall.position) < 10:
                    location.is_occupied_by_enemy = True
                    break
            else:
                # no townhall found at this location
                if location.is_occupied_by_enemy:
                    location.is_occupied_by_enemy = False
                    for position in self.enemy_base_built_times:
                        if position.manhattan_distance(location.expansion_position) < 10:
                            del self.enemy_base_built_times[position]
                            break
                    if self.newest_enemy_base and location.expansion_position.manhattan_distance(self.newest_enemy_base) < 10:
                        self.newest_enemy_base = None
                        max_time = -1
                        for position, build_time in self.enemy_base_built_times.items():
                            if build_time > max_time:
                                max_time = build_time
                                self.newest_enemy_base = position

            for scout in scout_units:
                if scout.position.manhattan_distance(location.scouting_position) < 1:
                    location.last_visited = self.bot.time
                    break

    def get_newest_enemy_base(self) -> Point2 | None:
        max_time = -1
        for position, build_time in self.enemy_base_built_times.items():
            if build_time > max_time:
                max_time = build_time
                self.newest_enemy_base = position
        return self.newest_enemy_base

    def get_next_enemy_expansion_scout_locations(self) -> List[ScoutingLocation]:
        next_locations: List[ScoutingLocation] = []
        # return next location in each order since they may differ
        for location in self.map.enemy_expansion_orders[ExpansionSelection.CLOSEST]:
            if not location.is_occupied_by_enemy:
                next_locations.append(location)
                break
        for location in self.map.enemy_expansion_orders[ExpansionSelection.AWAY_FROM_ENEMY]:
            if not location.is_occupied_by_enemy:
                next_locations.append(location)
                break
        return next_locations

    async def detect_enemy_builds(self):
        if self.enemy_race_confirmed is None:
            return
        if self.proxy_detected():
            await LogHelper.add_chat("proxy suspected")
            self.add_detected_build(BuildType.PROXY)
            self.add_detected_build(BuildType.RUSH)
        if self.bot.time < 60:
            rushing_enemy_workers = self.bot.enemy_units.filter(
                lambda u: u.distance_to(self.bot.start_location) - 15 < u.distance_to(self.bot.enemy_start_locations[0]))
            if rushing_enemy_workers.amount >= 3:
                await LogHelper.add_chat("worker rush detected")
                self.add_detected_build(BuildType.WORKER_RUSH)
                self.add_detected_build(BuildType.RUSH)
        if self.enemy_race_confirmed == Race.Zerg:
            early_pool = self.first_building_time.get(UnitTypeId.SPAWNINGPOOL, 9999) < 40
            no_gas = self.initial_scout_completed and self.number_seen(UnitTypeId.EXTRACTOR) == 0
            no_expansion = self.initial_scout_completed and self.number_seen(UnitTypeId.HATCHERY) == 1
            zergling_rush = self.enemy.get_total_count_of_type_seen(UnitTypeId.ZERGLING) >= 8 and self.bot.time < 180
            if early_pool:
                await LogHelper.add_chat("early pool detected")
            if no_gas:
                await LogHelper.add_chat("no gas detected")
            if no_expansion:
                await LogHelper.add_chat("no expansion detected")
            if zergling_rush:
                await LogHelper.add_chat("zergling rush detected")
                self.add_detected_build(BuildType.ZERGLING_RUSH)
            if early_pool or no_gas or no_expansion or zergling_rush:
                self.add_detected_build(BuildType.RUSH)
        elif self.enemy_race_confirmed == Race.Terran:
            # no_expansion = self.number_seen(UnitTypeId.COMMANDCENTER) == 1 and self.initial_scout.completed
            battlecruiser = self.bot.time < 360 and \
                (self.number_seen(UnitTypeId.FUSIONCORE) > 0 or
                 self.number_seen(UnitTypeId.BATTLECRUISER) > 0)
            if battlecruiser:
                await LogHelper.add_chat("battlecruiser rush detected")
                self.add_detected_build(BuildType.BATTLECRUISER_RUSH)
            multiple_barracks = not self.initial_scout_completed and self.number_seen(UnitTypeId.BARRACKS) > 1
            if multiple_barracks:
                await LogHelper.add_chat("multiple early barracks detected")
            # if no_expansion:
            #     await LogHelper.add_chat("no expansion detected")
            if multiple_barracks:
                self.add_detected_build(BuildType.RUSH)
        else:
            # Protoss
            lots_of_gateways = not self.initial_scout_completed and self.number_seen(UnitTypeId.GATEWAY) > 2
            no_expansion = self.initial_scout_completed and self.number_seen(UnitTypeId.NEXUS) == 1
            early_stargate = self.number_seen(UnitTypeId.STARGATE) > 0
            fleet_beacon = self.number_seen(UnitTypeId.FLEETBEACON) > 0
            if lots_of_gateways:
                await LogHelper.add_chat("lots of gateways detected")
            if no_expansion:
                await LogHelper.add_chat("no expansion detected")
            if early_stargate:
                await LogHelper.add_chat("stargate detected")
                self.add_detected_build(BuildType.STARGATE)
            if fleet_beacon:
                await LogHelper.add_chat("fleet beacon detected")
                self.add_detected_build(BuildType.FLEET_BEACON)
            if lots_of_gateways or no_expansion:
                self.add_detected_build(BuildType.RUSH)
            
            if self.bot.time < 180 and len(self.bot.enemy_units) > 0 and len(self.bot.enemy_units.closer_than(30, self.bot.start_location)) > 5:
                await LogHelper.add_chat("early army detected near base")
                self.add_detected_build(BuildType.RUSH)

    def number_seen(self, unit_type: UnitTypeId) -> int:
        return len(self.type_positions_seen.get(unit_type, []))

    def add_detected_build(self, build_type: BuildType):
        if build_type not in self.enemy_builds_detected:
            self.enemy_builds_detected[build_type] = self.bot.time

    def proxy_detected(self) -> bool:
        if self.enemy_race_confirmed is None or self.bot.time > 120:
            return False
        if self.proxy_buildings:
            return True
        if self.enemy_race_confirmed == Race.Zerg:
            # are zerg proxy a thing?
            return False
        if self.enemy_race_confirmed == Race.Terran:
            if self.bot.enemy_units(UnitTypeId.BATTLECRUISER) and self.number_seen(UnitTypeId.STARPORT) == 0:
                return True
            return self.enemy_main_scouted and self.number_seen(UnitTypeId.BARRACKS) == 0
        return self.bot.time > 100 and self.number_seen(UnitTypeId.GATEWAY) == 0
    
    def update_enemy_drop_locations(self):
        for transport in self.bot.enemy_units.of_type({UnitTypeId.MEDIVAC, UnitTypeId.WARPPRISM}):
            if transport not in self.enemy_drop_transports:
                if self.closest_distance_squared(transport, self.bot.townhalls) > 225:
                    # not near a base, not a drop
                    continue
                enemy_non_transports = self.bot.enemy_units.exclude_type({UnitTypeId.MEDIVAC, UnitTypeId.WARPPRISM})
                # exclude units that suddenly appeared since the transport was probably carrying them
                appeared_from_the_fog_enemies = enemy_non_transports.filter(
                    lambda u: u.tag not in self.enemy.suddenly_seen_units.tags)
                if appeared_from_the_fog_enemies:
                    nearby_allies = appeared_from_the_fog_enemies.closer_than(5, transport)
                    if nearby_allies:
                        # transport is not alone, not a drop
                        continue
                self.enemy_drop_transports.append(transport)
            if self.bot.in_pathing_grid(transport.position):
                i = len(self.enemy_drop_locations) - 1
                already_recorded = False
                while i >= 0:
                    drop_position, _ = self.enemy_drop_locations[i]
                    if transport.distance_to_squared(drop_position) < 6:
                        self.enemy_drop_locations[i] = (drop_position, self.bot.time)
                        already_recorded = True
                        break
                    i -= 1
                if not already_recorded:
                    self.enemy_drop_locations.append((transport.position, self.bot.time))
                    LogHelper.write_log_to_db(f"Enemy drop detected at {transport.position}")

    def get_recent_drop_locations(self, within_seconds: float) -> List[Point2]:
        recent_drops: List[Point2] = []
        i = len(self.enemy_drop_locations) - 1
        for drop_position, drop_time in self.enemy_drop_locations:
            if self.bot.time - drop_time <= within_seconds:
                recent_drops.append(drop_position)
        return recent_drops

    def update_proxy_buildings(self):
        i = len(self.proxy_buildings) - 1
        while i >= 0:
            if self.bot.is_visible(self.proxy_buildings[i].position):
                try:
                    self.proxy_buildings[i] = UnitReferenceHelper.get_updated_unit_reference(self.proxy_buildings[i])
                except Exception as e:
                    LogHelper.add_log(f"proxy building no longer detected: {self.proxy_buildings[i]}")
                    self.proxy_buildings.remove(self.proxy_buildings[i])
            i -= 1

        if self.bot.time < 420:
            enemy_main = self.map.enemy_expansion_orders[ExpansionSelection.CLOSEST][0]
            scouted_structures = self.bot.enemy_structures.filter(lambda s: s.is_visible)
            for structure in scouted_structures:
                if structure.position.manhattan_distance(self.bot.start_location) > structure.position.manhattan_distance(enemy_main.expansion_position):
                    continue
                for proxy_structure in self.proxy_buildings:
                    if structure.type_id == proxy_structure.type_id and structure.position.manhattan_distance(proxy_structure.position) < 1:
                        break
                else:
                    if structure.type_id not in (UnitTypeId.PYLON, UnitTypeId.PHOTONCANNON, UnitTypeId.PLANETARYFORTRESS, UnitTypeId.BUNKER):
                        self.proxy_buildings.append(structure)
                        LogHelper.add_log(f"proxy building detected: {structure}")
