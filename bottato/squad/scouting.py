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
    def __init__(self):
        self.buildings_seen: dict[UnitTypeId, list[int]] = {}
        self.worker_count: int = 0
        self.military_count: int = 0
        self.gas_taken: int = 0
        self.natural_expansion_time: float = None
        self.pool_start_time: float = None  # zerg specific
        self.first_building_time: dict[UnitTypeId, float] = {}
        self.enemy_race_confirmed: Race = None

    def add_building(self, building: Unit, time: float):
        if building.type_id not in self.buildings_seen:
            self.buildings_seen[building.type_id] = []
        if building.tag not in self.buildings_seen[building.type_id]:
            self.buildings_seen[building.type_id].append(building.tag)
        
        if building.type_id not in self.first_building_time:
            start_time = time - building.build_progress * building._type_data.cost.time / 22.4
            self.first_building_time[building.type_id] = start_time
        
    def get_summary(self) -> str:
        return (f"Intel: Race={self.enemy_race_confirmed}, "
                f"Buildings={dict(self.buildings_seen)}, "
                f"Units={dict(self.units_seen)}, "
                f"Workers={self.worker_count}, Military={self.military_count}, "
                f"Gas={self.gas_taken}")
    
    def number_seen(self, unit_type: UnitTypeId) -> int:
        return len(self.buildings_seen.get(unit_type, []))

class InitialScout(BaseSquad, GeometryMixin):
    def __init__(self, bot: BotAI, map: Map, enemy: Enemy):
        super().__init__(bot=bot, name="initial_scout")
        self.bot = bot
        self.map = map
        self.enemy = enemy
        
        self.unit: Unit = None
        self.completed: bool = False
        self.rush_detected: bool = False
        self.enemy_natural_delayed: bool = False
        self.extra_production_detected: bool = False
        self.main_scouted: bool = False
        
        # Timing parameters
        self.start_time = 30
        self.initial_scout_complete_time = 120  # Extended time for full scouting
        
        # Intel gathering
        self.intel = EnemyIntel()
        
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
        self.waypoints.append(enemy_start)
        
        # Add waypoints in expanding rings around the main base
        # for radius in [6, 10, 14]:
        for radius in [13]:
            for angle_degrees in range(0, 360, 45):  # 8 directions
                import math
                angle_radians = math.radians(angle_degrees)
                x_offset = radius * math.cos(angle_radians)
                y_offset = radius * math.sin(angle_radians)
                waypoint = Point2((enemy_start.x + x_offset, enemy_start.y + y_offset))
                if self.bot.in_pathing_grid(waypoint):
                    self.waypoints.append(waypoint)

        self.original_waypoints = list(self.waypoints)
        
        # Add natural expansion as final waypoint
        # self.waypoints.append(self.map.enemy_natural_position)
        
        logger.debug(f"Generated {len(self.waypoints)} scouting waypoints for enemy main base")

    def _catalog_visible_units(self):
        """Catalog all visible enemy units and buildings"""
        # Count buildings by type
        for building in self.bot.enemy_structures:
            self.intel.add_building(building, self.bot.time)
        
        # Count gas geysers being mined
        gas_count = 0
        for geyser in self.bot.vespene_geyser:
            if geyser.distance_to(self.bot.enemy_start_locations[0]) < 12:
                # Check if there's a refinery/extractor/assimilator on it
                for building in self.bot.enemy_structures:
                    if (building.type_id in (UnitTypeId.REFINERY, UnitTypeId.EXTRACTOR, UnitTypeId.ASSIMILATOR) 
                        and building.distance_to(geyser) < 2):
                        gas_count += 1
                        break
        self.intel.gas_taken = max(self.intel.gas_taken, gas_count)
        
        # Detect race if not already confirmed
        if not self.intel.enemy_race_confirmed and self.bot.enemy_structures:
            if self.bot.enemy_race != Race.Random:
                self.intel.enemy_race_confirmed = self.bot.enemy_race
            else:
                first_building = self.bot.enemy_structures[0]
                if first_building.type_id in (UnitTypeId.COMMANDCENTER, UnitTypeId.BARRACKS, UnitTypeId.SUPPLYDEPOT):
                    self.intel.enemy_race_confirmed = Race.Terran
                elif first_building.type_id in (UnitTypeId.NEXUS, UnitTypeId.PYLON, UnitTypeId.GATEWAY):
                    self.intel.enemy_race_confirmed = Race.Protoss
                elif first_building.type_id in (UnitTypeId.HATCHERY, UnitTypeId.SPAWNINGPOOL, UnitTypeId.OVERLORD):
                    self.intel.enemy_race_confirmed = Race.Zerg

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
        
        self._catalog_visible_units()
        
        if self.unit.health_percentage < 0.7 or self.bot.time > self.initial_scout_complete_time:
            self.waypoints = [self.map.enemy_natural_position]  # check natural before leaving
            if self.unit.distance_to(self.map.enemy_natural_position) < 9:
                self.completed = True
        else:
            i = len(self.waypoints) - 1
            while i >= 0:
                # remove waypoints as they are checked
                if self.unit.distance_to(self.waypoints[i]) <= 5:
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

    def rush_detected(self) -> bool:
        if self.proxy_detected():
            return True
        if self.intel.enemy_race_confirmed is None:
            return False
        if self.intel.enemy_race_confirmed == Race.Zerg:
            return self.intel.first_building_time.get(UnitTypeId.SPAWNINGPOOL, float('inf')) < 40 or self.main_scouted and self.intel.number_seen(UnitTypeId.EXTRACTOR) == 0
        if self.intel.enemy_race_confirmed == Race.Terran:
            return self.intel.number_seen(UnitTypeId.BARRACKS) > 1 and self.intel.number_seen(UnitTypeId.COMMANDCENTER) == 1
        return self.intel.number_seen(UnitTypeId.GATEWAY) > 1 and self.intel.number_seen(UnitTypeId.NEXUS) == 1
        return self.enemy_natural_delayed
    
    def proxy_detected(self) -> bool:
        if self.intel.enemy_race_confirmed is None:
            return False
        if self.intel.enemy_race_confirmed == Race.Zerg:
            # are zerg proxy a thing?
            return False
        if self.intel.enemy_race_confirmed == Race.Terran:
            return self.main_scouted and self.intel.number_seen(UnitTypeId.BARRACKS) == 0
        return self.main_scouted and self.intel.number_seen(UnitTypeId.GATEWAY) == 0
    
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
    
    def get_scouting_progress(self) -> float:
        """Get completion percentage of scouting waypoints"""
        if not self.waypoints:
            return 1.0
        return min(1.0, self.current_waypoint_index / len(self.waypoints))

class Scouting(BaseSquad, DebugMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, workers: Workers, military: Military):
        super().__init__(bot=bot, color=self.random_color(), name="scouting")
        self.bot = bot
        self.enemy = enemy
        self.map = map
        self.workers = workers
        self.military = military
        self.rush_is_detected: bool = False

        self.friendly_territory = Scout("friendly territory", self.bot, enemy)
        self.enemy_territory = Scout("enemy territory", self.bot, enemy)
        self.initial_scout = InitialScout(self.bot, self.map, self.enemy)
        self.newest_enemy_base = None

        # positions to scout
        self.empty_enemy_expansion_locations: list[Point2] = []
        # track occupied expansion positions so if they are destroyed we can add them back to empty_enemy_expansion_locations
        self.occupied_enemy_expansion_locations: dict[int, Point2] = {}
        # used to identify newest bases to attack
        self.enemy_base_built_times: dict[int, float] = {}

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
        enemy_townhalls = self.bot.enemy_structures.of_type(race_townhalls[self.bot.enemy_race])
        # add new townhalls to known enemy bases
        for townhall in enemy_townhalls:
            if townhall.tag not in self.enemy_base_built_times:
                self.enemy_base_built_times[townhall.tag] = self.bot.time
                for location in self.scouting_locations:
                    if location.position.manhattan_distance(townhall.position) < 10:
                        location.is_occupied_by_enemy = True
                        self.occupied_enemy_expansion_locations[townhall.tag] = location.position
                        self.newest_enemy_base = townhall.position
                        if location.position in self.empty_enemy_expansion_locations:
                            self.empty_enemy_expansion_locations.remove(location.position)
                        break

        for location in self.scouting_locations:
            if self.bot.is_visible(location.position):
                location.last_seen = self.bot.time

    def remove_enemy_base(self, base_tag: int):
        del self.enemy_base_built_times[base_tag]
        for occupied_expansion_tag, position in self.occupied_enemy_expansion_locations.items():
            if occupied_expansion_tag == base_tag:
                for location in self.scouting_locations:
                    if location.position.manhattan_distance(position) < 10:
                        location.is_occupied_by_enemy = False
                        break
                del self.occupied_enemy_expansion_locations[occupied_expansion_tag]
                self.empty_enemy_expansion_locations.append(position)
                break
        if self.newest_enemy_base.tag == base_tag:
            newest_base_tag: Unit = None
            newest_time: float = 0
            for base_tag, built_time in self.enemy_base_built_times.items():
                if built_time > newest_time:
                    newest_time = built_time
                    newest_base_tag = base_tag
            self.newest_enemy_base = self.occupied_enemy_expansion_locations[newest_base_tag] if newest_base_tag else None

    def get_newest_enemy_base(self) -> Point2:
        return self.newest_enemy_base
    
    def get_enemy_intel(self) -> EnemyIntel:
        """Get intelligence gathered by the initial scout"""
        return self.initial_scout.get_intel()
    
    def get_scout_progress(self) -> float:
        """Get the progress of initial scouting (0.0 to 1.0)"""
        return self.initial_scout.get_scouting_progress()

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
    def rush_detected(self) -> bool:
        self.rush_is_detected = self.rush_is_detected or self.initial_scout.rush_detected or self.bot.time < 180 and len(self.bot.enemy_units) > 0 and len(self.bot.enemy_units.closer_than(30, self.bot.start_location)) > 5
        return self.rush_is_detected
