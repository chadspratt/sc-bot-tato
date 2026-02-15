from loguru import logger
from typing import List

from cython_extensions.geometry import cy_distance_to, cy_distance_to_squared
from cython_extensions.units_utils import cy_closer_than, cy_closest_to
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from bottato.economy.workers import WorkerJobType, Workers
from bottato.enemy import Enemy
from bottato.enums import ScoutType
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.military import Military
from bottato.squad.scouting_location import ScoutingLocation
from bottato.squad.squad import Squad
from bottato.unit_reference_helper import UnitReferenceHelper


class Scout(Squad):
    def __init__(self, name, bot: BotAI, enemy: Enemy):
        self.name: str = name
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.unit: Unit | None = None
        self.scouting_locations: List[ScoutingLocation] = list()
        self.scouting_locations_index: int = 0
        self.closest_distance_to_next_location = 9999
        self.time_of_closest_distance = 9999
        self.complete = False
        super().__init__(bot=bot, name="scout")

    def __repr__(self):
        return f"{self.name} scouts: {self.unit}, locations: {self.scouting_locations}"

    def add_location(self, scouting_location: ScoutingLocation):
        self.scouting_locations.append(scouting_location)

    def traveling_salesman_sort(self, map: Map | None = None):
        """Sort scouting locations in traveling salesman order to minimize travel distance"""
        if not self.scouting_locations:
            return
        sorted_locations: List[ScoutingLocation] = []
        best_distance = float('inf')
        current_position = self.scouting_locations[0]
        sorted_unvisited = sorted(self.scouting_locations, key=lambda loc: current_position.scouting_position._distance_squared(loc.scouting_position))
        last_position = sorted_unvisited[-1]
        possible_routes: List[List[ScoutingLocation]] = self.get_routes([current_position], sorted_unvisited[1:-1])

        for route in possible_routes:
            total_distance = 0.0
            previous_location = route[0]
            route.append(last_position)
            for location in route[1:]:
                if map:
                    # add distance to nearest pathing grid point
                    path_points = map.get_path_points(previous_location.scouting_position, location.scouting_position)
                    for i in range(1, len(path_points)):
                        total_distance += cy_distance_to(path_points[i-1], path_points[i])
                else:
                    total_distance += cy_distance_to(previous_location.scouting_position, location.scouting_position)
                if total_distance > best_distance:
                    break
                previous_location = location
            else:
                best_distance = total_distance
                sorted_locations = route
        self.scouting_locations = sorted_locations

    def get_routes(self, current_route: List[ScoutingLocation], unvisited: List[ScoutingLocation]) -> List[List[ScoutingLocation]]:
        if not unvisited:
            return [current_route]
        routes: List[List[ScoutingLocation]] = []
        previous_location = current_route[-1]
        sorted_unvisited = sorted(unvisited, key=lambda loc: cy_distance_to_squared(previous_location.scouting_position, loc.scouting_position))
        for i in range(len(sorted_unvisited)):
            if i > 2:
                # limit branching factor for performance
                break
            next_location = sorted_unvisited[i]
            remaining = sorted_unvisited[:i] + sorted_unvisited[i+1:]
            new_route = current_route + [next_location]
            routes.extend(self.get_routes(new_route, remaining))
        return routes

    def contains_location(self, scouting_location: ScoutingLocation):
        return scouting_location in self.scouting_locations

    @property
    def scouts_needed(self) -> int:
        return 0 if self.unit else 1
    
    def needs(self, unit: Unit) -> bool:
        return unit.type_id in (UnitTypeId.SCV, UnitTypeId.MARINE, UnitTypeId.REAPER)

    def update_scout(self, military: Military, workers: Workers, scout_type: ScoutType = ScoutType.NONE):
        """Update unit reference for this scout"""
        if self.unit and self.unit.type_id == UnitTypeId.SCV:
            if self.unit.tag in workers.assignments_by_worker:
                assignment = workers.assignments_by_worker[self.unit.tag]
                if assignment.job_type != WorkerJobType.SCOUT:
                    # worker reassigned, release scout
                    self.unit = None
        if self.unit and self.unit.type_id == UnitTypeId.VIKINGFIGHTER:
            if military.enemies_in_base.filter(lambda u: u.is_flying):
                # viking needed to defend base, release scout
                military.transfer(self.unit, self, military.main_army)
                self.unit = None
        if self.unit:
            if scout_type == ScoutType.ANY:
                for location in self.scouting_locations:
                    if location.last_seen == 0:
                        break
                else:
                    # all locations have been seen, release scout
                    if self.unit.type_id == UnitTypeId.SCV:
                        workers.set_as_idle(self.unit)
                        self.unit = None
                        self.complete = True
                        return
            try:
                self.unit = UnitReferenceHelper.get_updated_unit_reference(self.unit)
                logger.debug(f"{self.name} scout {self.unit}")
            except UnitReferenceHelper.UnitNotFound:
                self.unit = None
                pass
        elif self.bot.time < 500 and scout_type == ScoutType.VIKING:
            if military.enemies_in_base.filter(lambda u: u.is_flying):
                # viking needed to defend base
                return
            # use initial viking to scout enemy army composition
            for unit in military.main_army.units:
                if unit.type_id == UnitTypeId.VIKINGFIGHTER:
                    military.transfer(unit, military.main_army, self)
                    self.unit = unit
                    break
        elif scout_type == ScoutType.ANY and not self.complete:
            self.unit = workers.get_scout(self.bot.game_info.map_center)
        elif self.bot.is_visible(self.bot.enemy_start_locations[0]) and \
                not cy_closer_than(self.bot.enemy_structures, 10, self.bot.enemy_start_locations[0]):
            # start territory scouting if enemy main is empty
            for unit in military.main_army.units:
                if self.needs(unit):
                    military.transfer(unit, military.main_army, self)
                    self.unit = unit
                    break
            else:
                # no marines or reapers, use a worker
                if self.bot.workers:
                    self.unit = workers.get_scout(self.bot.game_info.map_center)
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

        micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.unit)

        logger.debug(f"scout {self.unit} previous assignment: {assignment}")
        if self.unit.type_id == UnitTypeId.VIKINGFIGHTER:
            priority_enemy_targets = self.bot.enemy_units.of_type((UnitTypeId.BATTLECRUISER, UnitTypeId.BANSHEE, UnitTypeId.ORACLE, UnitTypeId.VOIDRAY))
            if priority_enemy_targets:
                await micro.scout(self.unit, cy_closest_to(self.unit.position, priority_enemy_targets).position)
                return

        distance_to_next_location = cy_distance_to(self.unit.position, assignment.scouting_position)
        if distance_to_next_location < self.closest_distance_to_next_location:
            self.closest_distance_to_next_location = distance_to_next_location
            self.time_of_closest_distance = self.bot.time
        # mark location as visited if can't get closer for 5 seconds
        if self.closest_distance_to_next_location < 30 and self.bot.time - self.time_of_closest_distance > 5:
            assignment.last_seen = self.bot.time
            assignment.last_visited = self.bot.time

        # move to next location if taking damage
        next_index = self.scouting_locations_index
        if self.unit.tag in new_damage_taken:
            next_index = (next_index + 1) % len(self.scouting_locations)
            assignment: ScoutingLocation = self.scouting_locations[next_index]
            logger.debug(f"scout {self.unit} took damage, changing assignment")

        # goal of viking scout is to see the army, not find unknown bases
        skip_occupied = self.unit.type_id != UnitTypeId.VIKINGFIGHTER
        while not assignment.needs_fresh_scouting(self.bot.time, skip_occupied):
        # while assignment.last_seen and self.bot.time - assignment.last_seen < 10 or assignment.is_occupied_by_enemy and skip_occupied:
            next_index = (next_index + 1) % len(self.scouting_locations)
            if next_index == self.scouting_locations_index:
                # full cycle, none need scouting
                break
            assignment: ScoutingLocation = self.scouting_locations[next_index]
            if not self.unit.is_flying:
                is_pathable = self.bot.client.query_pathing(self.unit.position, assignment.scouting_position)
                if not is_pathable:
                    assignment.last_seen = self.bot.time
            self.closest_distance_to_next_location = 9999
        self.scouting_locations_index = next_index
        LogHelper.add_log(f"scout {self.unit} new assignment: {assignment}")

        await micro.scout(self.unit, assignment.scouting_position)