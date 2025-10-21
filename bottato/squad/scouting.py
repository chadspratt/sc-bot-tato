from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.constants import UnitTypeId
from sc2.data import race_townhalls
from sc2.data import Race

from bottato.map.map import Map
from bottato.military import Military
from bottato.squad.base_squad import BaseSquad
from bottato.enemy import Enemy
from bottato.mixins import DebugMixin, GeometryMixin, UnitReferenceMixin
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.economy.workers import Workers


class ScoutingLocation:
    def __init__(self, position: Point2):
        self.position: Point2 = position
        self.last_seen: int = None
        self.is_occupied_by_enemy: bool = False

    def __repr__(self) -> str:
        return f"ScoutingLocation({self.position}, {self.last_seen})"


class Scout(BaseSquad, UnitReferenceMixin):
    def __init__(self, name, bot: BotAI, enemy: Enemy):
        self.name: str = name
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.unit: Unit = None
        self.scouting_locations: List[ScoutingLocation] = list()
        self.scouting_locations_index: int = 0
        super().__init__(bot=bot, name="scout")

    def __repr__(self):
        return f"{self.name} scouts: {self.unit}, locations: {self.scouting_locations}"

    def add_location(self, scouting_location: ScoutingLocation):
        self.scouting_locations.append(scouting_location)

    def contains_location(self, scouting_location: ScoutingLocation):
        return scouting_location in self.scouting_locations

    @property
    def scouts_needed(self) -> int:
        return 0 if self.unit else 1
    
    def needs(self, unit: Unit) -> bool:
        return unit.type_id in (UnitTypeId.SCV, UnitTypeId.MARINE, UnitTypeId.REAPER)

    def update_scout(self, military: Military, units_by_tag: dict[int, Unit]):
        """Update unit reference for this scout"""
        if self.unit:
            try:
                self.unit = self.get_updated_unit_reference(self.unit, units_by_tag)
                logger.debug(f"{self.name} scout {self.unit}")
            except self.UnitNotFound:
                self.unit = None
                pass
        elif self.bot.is_visible(self.bot.enemy_start_locations[0]) and not self.bot.enemy_structures.closer_than(10, self.bot.enemy_start_locations[0]):
            # start territory scouting if enemy main is empty
            if self.scouts_needed:
                for unit in military.main_army.units:
                    if self.needs(unit):
                        military.transfer(unit, military.main_army, self)
                        self.unit = unit
                        break
                else:
                    # no marines or reapers, use a worker
                    if self.bot.workers:
                        self.unit = self.bot.workers.random
                    else:
                        # unlikely, but fallback to any unit
                        for unit in military.main_army.units:
                            military.transfer(unit, military.main_army, self)
                            self.unit = unit
                            break

    async def move_scout(self, new_damage_taken: dict[int, float]):
        if not self.unit:
            return
        assignment: ScoutingLocation = self.scouting_locations[self.scouting_locations_index]
        logger.debug(f"scout {self.unit} previous assignment: {assignment}")

        micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.unit, self.bot, self.enemy)

        # move to next location if taking damage
        next_index = self.scouting_locations_index
        if self.unit.tag in new_damage_taken:
            next_index = (next_index + 1) % len(self.scouting_locations)
            assignment: ScoutingLocation = self.scouting_locations[next_index]
            logger.debug(f"scout {self.unit} took damage, changing assignment")

        while assignment.last_seen and self.bot.time - assignment.last_seen < 10 or assignment.is_occupied_by_enemy:
            next_index = (next_index + 1) % len(self.scouting_locations)
            if next_index == self.scouting_locations_index:
                # full cycle, none need scouting
                break
            assignment: ScoutingLocation = self.scouting_locations[next_index]
        self.scouting_locations_index = next_index
        logger.debug(f"scout {self.unit} new assignment: {assignment}")

        await micro.scout(self.unit, assignment.position)

class EnemyIntel:
    def __init__(self, bot: BotAI):
        self.bot = bot
        self.buildings_seen: dict[UnitTypeId, list[int]] = {}
        self.worker_count: int = 0
        self.military_count: int = 0
        self.natural_expansion_time: float = None
        self.pool_start_time: float = None  # zerg specific
        self.first_building_time: dict[UnitTypeId, float] = {}
        self.enemy_race_confirmed: Race = None

    def add_building(self, building: Unit, time: float):
        if building.type_id not in self.buildings_seen:
            self.buildings_seen[building.type_id] = []
        if building.position not in self.buildings_seen[building.type_id]:
            self.buildings_seen[building.type_id].append(building.position)
        
        if building.type_id not in self.first_building_time:
            start_time = time - building.build_progress * building._type_data.cost.time / 22.4
            self.first_building_time[building.type_id] = start_time
        
    def get_summary(self) -> str:
        return (f"Intel: Race={self.enemy_race_confirmed}, "
                f"Buildings={dict(self.buildings_seen)}, "
                f"Units={dict(self.units_seen)}, "
                f"Workers={self.worker_count}, Military={self.military_count}, ")
    
    def number_seen(self, unit_type: UnitTypeId) -> int:
        return len(self.buildings_seen.get(unit_type, []))

    def catalog_visible_units(self):
        """Catalog all visible enemy units and buildings"""
        # Count buildings by type
        for building in self.bot.enemy_structures:
            self.add_building(building, self.bot.time)
        
        # Detect race if not already confirmed
        if not self.enemy_race_confirmed and self.bot.enemy_structures:
            if self.bot.enemy_race != Race.Random:
                self.enemy_race_confirmed = self.bot.enemy_race
            else:
                first_building: Unit = self.bot.enemy_structures[0]
                self.enemy_race_confirmed = first_building.race

class InitialScout(BaseSquad, GeometryMixin):
    def __init__(self, bot: BotAI, map: Map, enemy: Enemy):
        super().__init__(bot=bot, name="initial_scout")
        self.bot = bot
        self.map = map
        self.enemy = enemy
        
        self.unit: Unit = None
        self.completed: bool = False
        self.enemy_natural_delayed: bool = False
        self.extra_production_detected: bool = False
        self.main_scouted: bool = False
        
        # Timing parameters
        self.start_time = 30
        self.initial_scout_complete_time = 120  # Extended time for full scouting
        
        # Scouting waypoints for systematic main base exploration
        self.waypoints: List[Point2] = []
        self.current_waypoint_index: int = 0
        self.waypoints_completed: bool = False
        
        # Initialize waypoints around enemy main
        self._generate_main_base_waypoints()

    def _generate_main_base_waypoints(self):
        """Generate systematic waypoints to explore the enemy main base"""
        enemy_start = self.bot.enemy_start_locations[0]
        
        # Create a systematic grid pattern around the enemy main base
        # Cover the main base area thoroughly
        # base_radius = 15  # Radius around main base to scout
        
        # Add the main base center
        # self.waypoints.append(enemy_start)
        
        # Add waypoints in expanding rings around the main base
        # for radius in [6, 10, 14]:
        for radius in [13]:
            for angle_degrees in range(0, 360, 15):
                import math
                angle_radians = math.radians(angle_degrees)
                x_offset = radius * math.cos(angle_radians)
                y_offset = radius * math.sin(angle_radians)
                waypoint = Point2((enemy_start.x + x_offset, enemy_start.y + y_offset))
                retries = 0
                while not self.bot.in_pathing_grid(waypoint) and retries < 5:
                    waypoint = waypoint.towards(enemy_start, 1)
                    retries += 1
                if retries != 5:
                    self.waypoints.append(waypoint)

        self.original_waypoints = list(self.waypoints)
        
        # Add natural expansion as final waypoint
        # self.waypoints.append(self.map.enemy_natural_position)
        
        logger.debug(f"Generated {len(self.waypoints)} scouting waypoints for enemy main base")

    def update_scout(self, workers: Workers, units_by_tag: dict[int, Unit]):
        if self.bot.time < self.start_time:
            # too early to scout
            return
            
        if self.unit:
            try:
                self.unit = self.get_updated_unit_reference(self.unit, units_by_tag)
            except self.UnitNotFound:
                self.unit = None
                return

            if self.completed:
                workers.set_as_idle(self.unit)
                self.unit = None
                return
                
        if not self.unit and not self.completed:
            # Get the first waypoint as initial target
            target = self.waypoints[0] if self.waypoints else self.map.enemy_natural_position
            self.unit = workers.get_scout(target)
    
    async def move_scout(self):
        if not self.unit or self.completed:
            return
        
        if self.unit.health_percentage < 0.7 or self.bot.time > self.initial_scout_complete_time:
            self.waypoints = [self.map.enemy_natural_position]  # check natural before leaving
            if self.unit.distance_to(self.map.enemy_natural_position) < 9:
                self.completed = True
        else:
            i = len(self.waypoints) - 1
            while i >= 0:
                # remove waypoints as they are checked
                if self.unit.distance_to(self.waypoints[i]) <= 5:
                    if not self.waypoints_completed and len(self.waypoints) == len(self.original_waypoints):
                        # first waypoint reached, reorder original waypoints to start from this one
                        self.original_waypoints = self.original_waypoints[i:] + self.original_waypoints[:i]
                        self.waypoints = list(self.original_waypoints)
                        self.waypoints.pop(0)
                        break
                    self.waypoints.pop(i)
                i -= 1
                
            # Check if we've completed all waypoints
            if len(self.waypoints) == 0:
                self.waypoints_completed = True
                self.main_scouted = True
                self.waypoints = list(self.original_waypoints)  # reset to keep scouting
            
        # for waypoint in self.waypoints:
        #     self.bot.client.debug_box2_out(self.convert_point2_to_3(waypoint))
            
        # Move to current waypoint
        if self.waypoints:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.unit, self.bot, self.enemy)
            await micro.scout(self.unit, self.waypoints[0])

class Scouting(BaseSquad, DebugMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, workers: Workers, military: Military):
        super().__init__(bot=bot, color=self.random_color(), name="scouting")
        self.bot = bot
        self.enemy = enemy
        self.map = map
        self.workers = workers
        self.military = military
        self.rush_is_detected: bool = False

        self.intel = EnemyIntel(self.bot)
        self.friendly_territory = Scout("friendly territory", self.bot, enemy)
        self.enemy_territory = Scout("enemy territory", self.bot, enemy)
        self.initial_scout = InitialScout(self.bot, self.map, self.enemy)
        self.newest_enemy_base = self.bot.enemy_start_locations[0]

        # positions to scout
        self.empty_enemy_expansion_locations: list[Point2] = []
        # used to identify newest bases to attack
        self.enemy_base_built_times: dict[Point2, float] = {self.bot.enemy_start_locations[0]: 0.0}

        # assign all expansions locations to either friendly or enemy territory
        self.scouting_locations: List[ScoutingLocation] = list()
        for expansion_location in self.bot.expansion_locations_list:
            self.scouting_locations.append(ScoutingLocation(expansion_location))
        nearest_locations_temp = sorted(self.scouting_locations, key=lambda location: (location.position - self.bot.start_location).length)
        enemy_nearest_locations_temp = sorted(self.scouting_locations, key=lambda location: (location.position - self.bot.enemy_start_locations[0]).length)
        for i in range(len(nearest_locations_temp)):
            if not self.enemy_territory.contains_location(nearest_locations_temp[i]):
                self.friendly_territory.add_location(nearest_locations_temp[i])
            if not self.friendly_territory.contains_location(enemy_nearest_locations_temp[i]):
                self.enemy_territory.add_location(enemy_nearest_locations_temp[i])
                self.empty_enemy_expansion_locations.append(enemy_nearest_locations_temp[i].position)

    def update_visibility(self):
        self.intel.catalog_visible_units()
        enemy_townhalls = self.bot.enemy_structures.of_type(race_townhalls[self.bot.enemy_race])
        # add new townhalls to known enemy bases
        for townhall in enemy_townhalls:
            if townhall.position not in self.enemy_base_built_times:
                self.enemy_base_built_times[townhall.position] = self.bot.time
                self.newest_enemy_base = townhall.position
        for location in self.scouting_locations:
            if self.bot.is_visible(location.position):
                location.last_seen = self.bot.time
            for townhall in enemy_townhalls:
                if location.position.manhattan_distance(townhall.position) < 10:
                    location.is_occupied_by_enemy = True
                    if location.position in self.empty_enemy_expansion_locations:
                        self.empty_enemy_expansion_locations.remove(location.position)
                    break
            else:
                # no townhall found at this location
                if location.is_occupied_by_enemy:
                    location.is_occupied_by_enemy = False
                    self.empty_enemy_expansion_locations.append(location.position)
                    for position in self.enemy_base_built_times:
                        if position.manhattan_distance(location.position) < 10:
                            del self.enemy_base_built_times[position]
                            break
                    if location.position == self.newest_enemy_base:
                        self.newest_enemy_base = None
                        max_time = -1
                        for position, build_time in self.enemy_base_built_times.items():
                            if build_time > max_time:
                                max_time = build_time
                                self.newest_enemy_base = position

    async def detect_rush(self) -> bool:
        if self.proxy_detected():
            await self.bot.client.chat_send("proxy suspected", False)
            return True
        if self.intel.enemy_race_confirmed is None:
            return False
        if self.intel.enemy_race_confirmed == Race.Zerg:
            early_pool = self.intel.first_building_time.get(UnitTypeId.SPAWNINGPOOL, float('inf')) < 40
            no_gas = self.initial_scout.completed and self.intel.number_seen(UnitTypeId.EXTRACTOR) == 0
            no_expansion = self.initial_scout.completed and self.intel.number_seen(UnitTypeId.HATCHERY) == 1
            if early_pool:
                await self.bot.client.chat_send("early pool detected", False)
            if no_gas:
                await self.bot.client.chat_send("no gas detected", False)
            if no_expansion:
                await self.bot.client.chat_send("no expansion detected", False)
            return early_pool or no_gas or no_expansion
        if self.intel.enemy_race_confirmed == Race.Terran:
            multiple_barracks = not self.initial_scout.completed and self.intel.number_seen(UnitTypeId.BARRACKS) > 1
            no_expansion = self.intel.number_seen(UnitTypeId.COMMANDCENTER) == 1 and self.initial_scout.completed
            if multiple_barracks and no_expansion:
                await self.bot.client.chat_send("multiple barracks and no expansion detected", False)
            return multiple_barracks and no_expansion
        # Protoss
        lots_of_gateways = not self.initial_scout.completed and self.intel.number_seen(UnitTypeId.GATEWAY) > 2
        no_expansion = self.initial_scout.completed and self.intel.number_seen(UnitTypeId.NEXUS) == 1
        if lots_of_gateways:
            await self.bot.client.chat_send("lots of gateways detected", False)
        if no_expansion:
            await self.bot.client.chat_send("no expansion detected", False)
        return lots_of_gateways or no_expansion
    
    def proxy_detected(self) -> bool:
        if self.intel.enemy_race_confirmed is None:
            return False
        if self.intel.enemy_race_confirmed == Race.Zerg:
            # are zerg proxy a thing?
            return False
        if self.intel.enemy_race_confirmed == Race.Terran:
            return self.initial_scout.main_scouted and self.intel.number_seen(UnitTypeId.BARRACKS) == 0
        return self.initial_scout.main_scouted and self.intel.number_seen(UnitTypeId.GATEWAY) == 0

    def enemy_natural_is_built(self) -> bool:
        enemy_townhalls = self.bot.enemy_structures.of_type([
            UnitTypeId.COMMANDCENTER,
            UnitTypeId.ORBITALCOMMAND,
            UnitTypeId.PLANETARYFORTRESS,
            UnitTypeId.HATCHERY,
            UnitTypeId.LAIR,
            UnitTypeId.HIVE,
            UnitTypeId.NEXUS
        ])
        for th in enemy_townhalls:
            if th.position.distance_to(self.map.enemy_natural_position) < 5:
                if not self.intel.natural_expansion_time:
                    self.intel.natural_expansion_time = self.bot.time
                return True
        return False
    
    def get_intel(self) -> EnemyIntel:
        """Get the gathered intelligence about the enemy"""
        return self.intel

    def get_newest_enemy_base(self) -> Point2:
        return self.newest_enemy_base

    async def scout(self, new_damage_taken: dict[int, float], units_by_tag: dict[int, Unit]):
        # Update scout unit references
        self.friendly_territory.update_scout(self.military, units_by_tag)
        self.enemy_territory.update_scout(self.military, units_by_tag)
        self.initial_scout.update_scout(self.workers, units_by_tag)

        self.update_visibility()

        await self.initial_scout.move_scout()

        # Move scouts
        await self.friendly_territory.move_scout(new_damage_taken)
        await self.enemy_territory.move_scout(new_damage_taken)

    @property
    async def rush_detected(self) -> bool:
        self.rush_is_detected = self.rush_is_detected or await self.detect_rush() or self.bot.time < 180 and len(self.bot.enemy_units) > 0 and len(self.bot.enemy_units.closer_than(30, self.bot.start_location)) > 5
        return self.rush_is_detected
