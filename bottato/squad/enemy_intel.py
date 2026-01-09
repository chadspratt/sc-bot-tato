from typing import List

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.data import race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.squad.scouting_location import ScoutingLocation

class EnemyIntel:
    def __init__(self, bot: BotAI, map: Map):
        self.bot = bot
        self.map = map
        self.types_seen: dict[UnitTypeId, List[Point2]] = {}
        self.worker_count: int = 0
        self.military_count: int = 0
        self.natural_expansion_time: float | None = None
        self.pool_start_time: float | None = None  # zerg specific
        self.first_building_time: dict[UnitTypeId, float] = {}
        self.enemy_race_confirmed: Race | None = None
        self.scouting_locations: List[ScoutingLocation] = list()
        for expansion_location in self.bot.expansion_locations_list:
            self.scouting_locations.append(ScoutingLocation(expansion_location.towards(self.bot.game_info.map_center, -5)))
        self.enemy_base_built_times: dict[Point2, float] = {self.bot.enemy_start_locations[0]: 0.0}

    def add_type(self, unit: Unit, time: float):
        if unit.is_structure:
            if unit.type_id not in self.types_seen:
                self.types_seen[unit.type_id] = []
            if unit.position not in self.types_seen[unit.type_id]:
                self.types_seen[unit.type_id].append(unit.position)
        elif unit.type_id not in self.types_seen:
            self.types_seen[unit.type_id] = [unit.position]
            LogHelper.add_log(f"EnemyIntel: first seen {unit.type_id} at time {time:.1f}")
        
        if unit.type_id not in self.first_building_time:
            start_time = time - unit.build_progress * unit._type_data.cost.time / 22.4 # type: ignore
            self.first_building_time[unit.type_id] = start_time
            LogHelper.add_log(f"EnemyIntel: first {unit.type_id} started at time {start_time:.1f}")
        
    def get_summary(self) -> str:
        return (f"Intel: Race={self.enemy_race_confirmed}, "
                f"Buildings={dict(self.types_seen)}, "
                # f"Units={dict(self.units_seen)}, "
                f"Workers={self.worker_count}, Military={self.military_count}, ")
    
    def number_seen(self, unit_type: UnitTypeId) -> int:
        return len(self.types_seen.get(unit_type, []))

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

    def update_location_visibility(self, scout_units: List[Unit]):
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
                    break
            else:
                # no townhall found at this location
                if location.is_occupied_by_enemy:
                    location.is_occupied_by_enemy = False
                    for position in self.enemy_base_built_times:
                        if position.manhattan_distance(location.position) < 10:
                            del self.enemy_base_built_times[position]
                            break
                    if self.newest_enemy_base and location.position.manhattan_distance(self.newest_enemy_base) < 10:
                        self.newest_enemy_base = None
                        max_time = -1
                        for position, build_time in self.enemy_base_built_times.items():
                            if build_time > max_time:
                                max_time = build_time
                                self.newest_enemy_base = position
            
            for scout in scout_units:
                if scout.position.manhattan_distance(location.position) < 1:
                    location.last_visited = self.bot.time
                    break

    def get_newest_enemy_base(self) -> Point2 | None:
        max_time = -1
        for position, build_time in self.enemy_base_built_times.items():
            if build_time > max_time:
                max_time = build_time
                self.newest_enemy_base = position
        return self.newest_enemy_base

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
                if not self.natural_expansion_time:
                    self.natural_expansion_time = self.bot.time
                return True
        return False