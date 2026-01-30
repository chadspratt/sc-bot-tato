from __future__ import annotations
import math
from typing import List, Dict, Set, Tuple

from loguru import logger
import numpy as np

from sc2.bot_ai import BotAI
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.enums import ExpansionSelection
from bottato.log_helper import LogHelper
from bottato.map.influence_maps import InfluenceMaps
from bottato.map.zone import Path, Zone
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.squad.scouting_location import ScoutingLocation
from bottato.unit_types import UnitTypes


class Map(GeometryMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.influence_maps = InfluenceMaps(self.bot)
        self.zone_lookup_by_coord: Dict[Tuple, Zone] = {}
        self.cached_neighbors8: Dict[Tuple, Set[Tuple]] = {}
        self.cached_neighbors4: Dict[Tuple, Set[Tuple]] = {}
        self.coords_by_distance: Dict[int, List[Tuple]] = {}
        self.init_distance_from_edge(self.influence_maps.get_long_range_grid())
        self.zones: Dict[int, Zone] = {}
        logger.debug(f"zones {self.zones}")
        self.first_draw = True
        self.last_refresh_time = 0
        self.natural_position: Point2 = self.bot.start_location
        self.enemy_natural_position: Point2 = self.bot.enemy_start_locations[0]
        self.all_damage_by_position: dict[Point2, List[Tuple[float, float]]] = {}
        self.expansion_orders: Dict[ExpansionSelection, List[ScoutingLocation]] = {
            ExpansionSelection.CLOSEST: [],
            ExpansionSelection.AWAY_FROM_ENEMY: []
        }
        self.reaper_cliff_positions: Set[Point2] = set()
        self.enemy_expansion_orders: Dict[ExpansionSelection, List[ScoutingLocation]] = {
            ExpansionSelection.CLOSEST: [],
            ExpansionSelection.AWAY_FROM_ENEMY: []
        }

    async def init(self, scouting_locations: List[ScoutingLocation]):
        self.scouting_locations = scouting_locations
        self.zones: Dict[int, Zone] = await self.init_zones(self.distance_from_edge)
        self.natural_position = await self.get_natural_position(self.bot.start_location)
        self.enemy_natural_position = await self.get_natural_position(self.bot.enemy_start_locations[0])
        self.init_expansion_orders()

    def init_expansion_orders(self):
        # uses pathing so has to be called after map is initialized
        self.expansion_orders[ExpansionSelection.CLOSEST] = sorted(
            self.scouting_locations,
            key=lambda loc: loc.expansion_position.distance_to(self.bot.start_location)
        )
        self.expansion_orders[ExpansionSelection.AWAY_FROM_ENEMY] = sorted(
            self.scouting_locations,
                key=lambda loc: self._distance_minus_enemy_distance(
                    loc,
                    self.bot.start_location,
                    self.bot.enemy_start_locations[0])
        )
        # compute both for enemy because we don't know which they use
        self.enemy_expansion_orders[ExpansionSelection.CLOSEST] = sorted(
            self.scouting_locations,
            key=lambda loc: loc.expansion_position.distance_to(self.bot.enemy_start_locations[0])
        )
        self.enemy_expansion_orders[ExpansionSelection.AWAY_FROM_ENEMY] = sorted(
            self.scouting_locations,
                key=lambda loc: self._distance_minus_enemy_distance(
                    loc,
                    self.bot.enemy_start_locations[0],
                    self.bot.start_location)
        )
    
    def get_next_expansion(self, selection: ExpansionSelection = ExpansionSelection.AWAY_FROM_ENEMY) -> Point2 | None:
        for location in self.expansion_orders[selection]:
            if not self.unit_is_closer_than(location.expansion_position, self.bot.townhalls, 5):
                return location.expansion_position
        return None

    previous_reaper_elevations: Dict[int, float] = {}
    @timed_async
    async def refresh_map(self):
        for reaper in self.bot.units(UnitTypeId.REAPER):
            if reaper.tag not in self.previous_reaper_elevations:
                self.previous_reaper_elevations[reaper.tag] = self.bot.get_terrain_z_height(reaper.position)
            else:
                previous_elevation = self.previous_reaper_elevations[reaper.tag]
                current_elevation = self.bot.get_terrain_z_height(reaper.position)
                if abs(current_elevation - previous_elevation) > 1:
                    # elevation changed significantly, likely jumped a cliff
                    if reaper.position.rounded not in self.reaper_cliff_positions:
                        LogHelper.write_log_to_db("Reaper cliff", str(reaper.position.rounded))
                        self.reaper_cliff_positions.add(reaper.position.rounded)
                self.previous_reaper_elevations[reaper.tag] = current_elevation

        if self.influence_maps.destructables_changed():
            self.init_distance_from_edge(self.influence_maps.get_long_range_grid())
            self.zones: Dict[int, Zone] = await self.init_zones(self.distance_from_edge)
            for position, damage_list in self.all_damage_by_position.items():
                zone = self.zone_lookup_by_coord.get((position.x, position.y))
                if zone:
                    for damage, time in damage_list:
                        zone.add_damage(damage, time)
            self.last_refresh_time = self.bot.time

    @timed
    def init_distance_from_edge(self, pathing_grid: np.ndarray):
        self.distance_from_edge: Dict[Tuple, int] = {}
        self.coords_by_distance.clear()
        # init array with unpathable and put 9999 placeholder for other spots
        previous_layer = []
        next_layer = []
        unpathable = []

        self.coords_by_distance[0] = []
        for x in range(pathing_grid.shape[0]):
            for y in range(pathing_grid.shape[1]):
                coords = (x, y)
                if pathing_grid[coords] == 0:
                    next_layer.append(coords)
                    unpathable.append(coords)
                    self.distance_from_edge[coords] = 0
                    self.coords_by_distance[0].append(coords)

        current_distance = 0
        while next_layer:
            previous_layer = next_layer
            current_distance += 1
            self.coords_by_distance[current_distance] = []
            next_layer = []
            # logger.debug(f"current layer {previous_layer}")
            try:
                for previous_coord in previous_layer:
                    neighbors = self.neighbors4(previous_coord)
                    for neighbor in neighbors:
                        # logger.debug(f"neighbor of {previous_coord}: {neighbor}")
                        if neighbor not in self.distance_from_edge:
                            self.distance_from_edge[neighbor] = current_distance
                            # if not self.has_higher_neighbor(neighbor, self.distance_from_edge):
                            self.coords_by_distance[current_distance].append(neighbor)
                            # logger.debug(f"self.distance_from_edge {neighbor} is {self.distance_from_edge[neighbor]}")
                            next_layer.append(neighbor)
            except Exception as e:
                logger.debug(f"error calculating distance from edge at distance {current_distance}: {e}")

    def get_distance_from_edge(self, point: Point2) -> int:
        coords = (point.x, point.y)
        if coords in self.distance_from_edge:
            return self.distance_from_edge[coords]
        return 0

    # used for expanding inward from edge. if starting coords are unpathable, all neighbors are included
    # otherwise only neighbors of similar height are included
    def neighbors4(self, coords) -> Set[Tuple]:
        if coords not in self.cached_neighbors4:
            max_x = self.bot.game_info.pathing_grid.width - 1
            max_y = self.bot.game_info.pathing_grid.height - 1
            neighbors: Set[Tuple] = set()
            self.cached_neighbors4[coords] = neighbors

            candidates = []
            if coords[0] > 0:
                candidates.append((coords[0] - 1, coords[1]))
            if coords[1] > 0:
                candidates.append((coords[0], coords[1] - 1))
            if coords[1] < max_y:
                candidates.append((coords[0], coords[1] + 1))
            if coords[0] < max_x:
                candidates.append((coords[0] + 1, coords[1]))

            if coords in self.distance_from_edge and self.distance_from_edge[coords] == 0:
                neighbors.update(candidates)
            else:
                coord_height = self.bot.get_terrain_z_height(Point2(coords))
                for candidate in candidates:
                    self.add_if_similar_height(candidate, coord_height, neighbors)
        return self.cached_neighbors4[coords]

    # used for expanding outward from furthest points from edge
    # if starting coords are unpathable, only unpathable neighbors are included
    # otherwise only neighbors of similar height are included
    def neighbors8(self, coords: Tuple) -> Set[Tuple]:
        if coords not in self.cached_neighbors8:
            max_x = self.bot.game_info.pathing_grid.width - 1
            max_y = self.bot.game_info.pathing_grid.height - 1
            neighbors: Set[Tuple] = set()
            self.cached_neighbors8[coords] = neighbors

            candidates = []
            if coords[0] > 0:
                if coords[1] > 0:
                    candidates.append((coords[0] - 1, coords[1] - 1))
                candidates.append((coords[0] - 1, coords[1]))
                if coords[1] < max_y:
                    candidates.append((coords[0] - 1, coords[1] + 1))
            if coords[1] > 0:
                candidates.append((coords[0], coords[1] - 1))
            if coords[1] < max_y:
                candidates.append((coords[0], coords[1] + 1))
            if coords[0] < max_x:
                if coords[1] > 0:
                    candidates.append((coords[0] + 1, coords[1] - 1))
                candidates.append((coords[0] + 1, coords[1]))
                if coords[1] < max_y:
                    candidates.append((coords[0] + 1, coords[1] + 1))

            if coords in self.distance_from_edge and self.distance_from_edge[coords] == 0:
                # only add neighbors that are also unpathable
                for candidate in candidates:
                    if candidate in self.distance_from_edge and self.distance_from_edge[candidate] == 0:
                        neighbors.add(candidate)
            else:
                coord_height = self.bot.get_terrain_z_height(Point2(coords))
                for candidate in candidates:
                    self.add_if_similar_height(candidate, coord_height, neighbors)
        return self.cached_neighbors8[coords]

    def add_if_similar_height(self, coords, height, neighbors: Set[Tuple]):
        neighbor_height = self.bot.get_terrain_z_height(Point2(coords))
        if abs(height - neighbor_height) < 0.5:
            neighbors.add(coords)

    # def has_higher_neighbor(self, coords: Tuple, distance_from_edge) -> bool:
    #     distance = distance_from_edge[coords]
    #     for neighbor in self.neighbors8(coords):
    #         if neighbor in distance_from_edge and distance_from_edge[neighbor] > distance:
    #             return True
    #     return False

    @timed_async
    async def init_zones(self, distance_from_edge: Dict[Tuple, int]) -> Dict[int, Zone]:
        coords: Tuple
        zone_index = 0
        zones: Dict[int, Zone] = {}
        distances: List[int] = sorted(self.coords_by_distance, reverse=True)
        zones_to_remove = []
        self.zone_lookup_by_coord.clear()
        logger.debug(f"distances {distances}")
        for distance in distances:
            zone: Zone
            for zone in zones.values():
                points_to_check: List[Tuple] = zone.unchecked_points
                zone.unchecked_points = []
                while points_to_check:
                    next_point = points_to_check.pop()
                    current_distance_to_edge = distance_from_edge[next_point]
                    neighbors = self.neighbors8(next_point)
                    neighbor: Tuple
                    # expand to any neighbors that are closer to the edge (won't push in to next zone)
                    for neighbor in neighbors:
                        try:
                            point_zone = self.zone_lookup_by_coord[neighbor]
                            if point_zone.id == zone.id or point_zone in zone.adjacent_zones:
                                # skip duplicates in same zone or already adjacent zones
                                continue
                            average_midpoint1 = Point2.center([Point2(c) for c in zone.coords])
                            average_midpoint2 = Point2.center([Point2(c) for c in point_zone.coords])
                            midpoint_distance = average_midpoint1.distance_to(average_midpoint2)
                            if midpoint_distance < 3 or current_distance_to_edge == distance_from_edge[neighbor] and midpoint_distance < 6:
                                # merge zones if the result won't be too large
                                for coords in point_zone.coords:
                                    self.zone_lookup_by_coord[coords] = zone
                                points_to_check.extend(point_zone.unchecked_points)
                                zones_to_remove.append(point_zone)
                                zone.merge_with(point_zone)
                            elif distance_from_edge[neighbor] > 0:
                                # check that elevation is similar
                                next_point_point: Point2 = Point2(next_point)
                                neighbor_point: Point2 = Point2(neighbor)
                                if abs(self.bot.get_terrain_z_height(next_point_point) - self.bot.get_terrain_z_height(neighbor_point)) < 1:
                                    # check that the zones are actually close and pathable
                                    # actual_distance = await self.bot.client.query_pathing(average_midpoint1, average_midpoint2)
                                    actual_distance = await self.bot.client.query_pathing(next_point_point, neighbor_point)
                                    # if actual_distance is not None and actual_distance < midpoint_distance * 1.2:
                                    if actual_distance is not None and actual_distance < 2:
                                        zone.add_adjacent_zone(point_zone)
                        except KeyError:
                            # unassigned point, check if closer to edge
                            neighbor_distance = distance_from_edge[neighbor]
                            # match lower points or equal height
                            if (neighbor_distance <= current_distance_to_edge):
                                self.zone_lookup_by_coord[neighbor] = zone
                                zone.coords.append(neighbor)
                                zone.unchecked_points.append(neighbor)

            if distance > 1:
                # create new zones from this layer's coords
                distance_coords = self.coords_by_distance[distance]
                logger.debug(f"creating zones from distance {distance} points {distance_coords}")
                for coords in distance_coords:
                    if coords in self.zone_lookup_by_coord:
                        # already in a zone or not a local max
                        continue
                    # new zone
                    new_zone = Zone(zone_index, coords, distance_from_edge[coords])
                    zones[new_zone.id] = new_zone
                    zone_index += 1
                    self.zone_lookup_by_coord[coords] = new_zone

        # add unpathable points to nearest zone
        remaining_unchecked = True
        while remaining_unchecked:
            remaining_unchecked = False
            for zone in zones.values():
                points_to_check: List[Tuple] = zone.unchecked_points
                zone.unchecked_points = []
                if points_to_check:
                    remaining_unchecked = True
                    while points_to_check:
                        next_point = points_to_check.pop()
                        # current_distance_to_edge = distance_from_edge[next_point]
                        neighbors = self.neighbors8(next_point)
                        neighbor: Tuple
                        for neighbor in neighbors:
                            if neighbor not in self.zone_lookup_by_coord:
                                self.zone_lookup_by_coord[neighbor] = zone
                                zone.coords.append(neighbor)
                                zone.unchecked_points.append(neighbor)

        for removed_zone in zones_to_remove:
            # zone = zones[removed_zone_id]
            del zones[removed_zone.id]
            for zone in zones.values():
                zone.remove_adjacent_zone(removed_zone)
                if removed_zone in zone.adjacent_zones:
                    zone.adjacent_zones.remove(removed_zone)

        for zone in zones.values():
            all_point2s = [Point2(coord) for coord in zone.coords if self.distance_from_edge[coord] > 0]
            zone.midpoint = Point2.center(all_point2s)

        logger.debug(f"all zones ({len(zones)}){zones}")
        return zones

    def get_shortest_path(self, units: Units, end: Point2) -> List[Point2]:
        shortest_distance = 9999
        shortest_path: List[Point2] = []
        for unit in units:
            path_points = self.get_path_points(unit.position, end)
            distance = 0
            previous_point: Point2 | None = None
            for path_point in path_points:
                if previous_point is None:
                    previous_point = path_point
                else:
                    distance += previous_point.distance_to(path_point)
                    previous_point = path_point
            if distance < shortest_distance:
                shortest_distance = distance
                shortest_path = path_points

        return shortest_path
    
    def get_closest_unit_by_path(self, units: Units, end: Point2) -> Unit:
        shortest_distance = 9999
        closest_unit: Unit | None = None
        for unit in units:
            path = self.get_path(unit.position, end)
            if path.length < shortest_distance:
                shortest_distance = path.length
                closest_unit = unit
        if closest_unit is None:
            # fallback to direct distance
            closest_unit = units.closest_to(end)
            self.get_path(units[0].position, end)
        return closest_unit

    def get_closest_position_by_path(self, start: Point2, positions: List[Point2]) -> Point2:
        assert len(positions) > 0
        shortest_distance = 9999
        closest_position: Point2 = positions[0]
        for position in positions:
            path = self.get_path(start, position)
            if path.length < shortest_distance:
                shortest_distance = path.length
                closest_position = position
        if closest_position is None:
            for position in positions:
                distance = position.distance_to(end)
                if distance < shortest_distance:
                    shortest_distance = distance
                    closest_position = position
        return closest_position
    
    def get_distances_by_path(self, start: Point2, positions: List[Point2]) -> Dict[Point2, float]:
        distances_by_position: Dict[Point2, float] = {}
        position: Point2
        for position in positions:
            path = self.get_path(start, position)
            distances_by_position[position] = path.length
        return distances_by_position
    
    def get_unit_distances_by_path(self, start: Point2, units: Units) -> Dict[Unit, float]:
        distances_by_unit: Dict[Unit, float] = {}
        for unit in units:
            path = self.get_path(start, unit.position)
            distances_by_unit[unit] = path.length
        return distances_by_unit

    @timed
    def get_path_points(self, start: Point2, end: Point2) -> List[Point2]:
        point2_path: List[Point2] = [start]
        zone: Zone
        path: Path = self.get_path(start, end)
        if path.length < 9999:
            logger.debug(f"found path {path}")
            for zone in path.zones[1:-1]:
                if zone.midpoint != point2_path[-1]:
                    point2_path.append(zone.midpoint)
            if end != point2_path[-1]:
                point2_path.append(end)
        return point2_path

    def get_path(self, start: Point2, end: Point2) -> Path:
        start_rounded: Point2 = start.rounded
        end_rounded: Point2 = end.rounded
        try:
            start_zone = self.zone_lookup_by_coord[(start_rounded.x, start_rounded.y)]
            end_zone = self.zone_lookup_by_coord[(end_rounded.x, end_rounded.y)]
        except KeyError:
            return Path([], math.inf)
        return start_zone.path_to(end_zone)

    @timed
    def get_pathable_position(self, position: Point2, unit: Unit) -> Point2:
        grid = self.ground_grid
        if unit.is_cloaked:
            grid = self.detection_grid
        elif unit.is_flying:
            grid = self.anti_air_grid
        candidates = self.influence_maps.find_lowest_cost_points(position, 4, grid)
        if candidates is None:
            pathable_position = position
        else:
            # XXX maybe cache this for performance, would need to use rounded position and store a sorted list of closest positions
            # most lookups should only have to look at first few candidates
            pathable_position: Point2 = self.influence_maps.closest_towards_point(candidates, position)
            try:
                position_cost = grid[int(position.y), int(position.x)]
            except IndexError:
                position_cost = np.inf
            try:
                pathable_cost = grid[int(pathable_position.x), int(pathable_position.y)]
            except IndexError:
                pathable_position = self.clamp_position_to_map_bounds(pathable_position, self.bot)
                pathable_cost = grid[int(pathable_position.x), int(pathable_position.y)]
            if position_cost <= pathable_cost and pathable_position._distance_squared(position) < 2.25:
                pathable_position = position
        if unit:
            self.influence_maps.add_cost((pathable_position[0], pathable_position[1]), unit.radius, self.ground_grid, np.inf)
        return pathable_position

    anti_air_structures: Set[UnitTypeId] = set([
        UnitTypeId.MISSILETURRET,
        UnitTypeId.BUNKER,
        UnitTypeId.PHOTONCANNON,
        UnitTypeId.SPORECRAWLER,
    ])
    @timed
    def update_influence_maps(self, damage_by_position: dict[Point2, float]) -> None:
        self.ground_grid = self.influence_maps.get_pyastar_grid()
        self.detection_grid = self.influence_maps.get_clean_air_grid()
        self.anti_air_grid = self.influence_maps.get_clean_air_grid()

        for position, damage in damage_by_position.items():
            zone = self.zone_lookup_by_coord.get((position.x, position.y))
            if zone:
                zone.add_damage(damage, self.bot.time)
            if position not in self.all_damage_by_position:
                self.all_damage_by_position[position] = []
            self.all_damage_by_position[position].append((damage, self.bot.time))

        cutoff_time = self.bot.time - 10
        for position, damage_list in self.all_damage_by_position.items():
            total_damage = 0.0
            for damage, time in damage_list:
                if time < cutoff_time:
                    continue
                total_damage += damage
            if total_damage > 0:
                self.influence_maps.add_cost((position[0], position[1]), 1.5, self.ground_grid, total_damage)
        
        for enemy in self.bot.all_enemy_units:
            if enemy.is_detector:
                self.influence_maps.add_cost((enemy.position[0], enemy.position[1]), enemy.sight_range + 1.5, self.detection_grid)
            if enemy.type_id in self.anti_air_structures and enemy.is_ready:
                self.influence_maps.add_cost((enemy.position[0], enemy.position[1]), UnitTypes.air_range(enemy) + 1.5, self.anti_air_grid)
        for effect in self.bot.state.effects:
            if effect.id == EffectId.SCANNERSWEEP:
                for position in effect.positions:
                    self.influence_maps.add_cost((position[0], position[1]), 14, self.detection_grid, np.inf)
        
        # self.draw_influence()
    
    async def get_natural_position(self, start_position: Point2) -> Point2:
        """Find natural location, given friendly or enemy start position"""
        closest = start_position
        distance = math.inf
        for el in self.bot.expansion_locations_list:
            d = await self.bot.client.query_pathing(start_position, el)
            if d is None:
                continue

            if d < distance:
                distance = d
                closest = el

        return closest
    
    def _distance_minus_enemy_distance(self, location: ScoutingLocation, start_position: Point2, enemy_start_position: Point2) -> float:
        """Helper function for sorting expansions by distance from enemy."""
        path = self.get_path(start_position, location.expansion_position)
        return path.length - location.expansion_position.distance_to(enemy_start_position)

    checked_zones = set()
    zones_to_check: List[Zone] = []
    async def get_non_visible_position_in_main(self) -> Point2 | None:
        if not self.zones_to_check:
            start_location = self.bot.start_location.rounded
            main_zone = self.zone_lookup_by_coord.get((start_location.x, start_location.y))
            if main_zone:
                self.zones_to_check.append(main_zone)
        while self.zones_to_check:
            current_zone = self.zones_to_check.pop(0)
            for coord in current_zone.coords:
                point = Point2(coord)
                if not self.bot.is_visible(point):
                    # can_place not reliable, also check terrain height
                    terrain_height = self.bot.get_terrain_z_height(point)
                    if terrain_height > 0:
                        # also avoid blocking natural with depot
                        if self.natural_position and point.distance_to(self.natural_position) <= 4:
                            continue
                        can_place = await self.bot.can_place(UnitTypeId.SUPPLYDEPOT, [point])
                        if can_place[0]:
                            self.zones_to_check.insert(0, current_zone)
                            return point
            self.checked_zones.add(current_zone)
            for adjacent_zone in current_zone.adjacent_zones:
                if adjacent_zone not in self.checked_zones:
                    self.zones_to_check.append(adjacent_zone)
        return None

    def draw_influence(self) -> None:
        # self.influence_maps.draw_influence_in_game(self.ground_grid, 1, 2000)
        self.influence_maps.draw_influence_in_game(self.detection_grid, 1, 2000)
        return

    @timed
    def draw(self) -> None:
        for zone_id in self.zones:
            zone = self.zones[zone_id]
            if zone.midpoint3 is not None:
                continue
            for coord in zone.coords:
                if self.distance_from_edge[coord] > 0:
                    zone.points_for_drawing[coord] = self.convert_point2_to_3(Point2(coord), self.bot)
            zone.midpoint3 = self.convert_point2_to_3(zone.midpoint, self.bot)
            for midpoint in zone.all_midpoints:
                zone.all_midpoints3.append(self.convert_point2_to_3(midpoint, self.bot))


        for zone_id in self.zones:
            zone = self.zones[zone_id]
            color = (zone.id % 255, (128 + zone.id) % 255, abs(255 - zone.id) % 255)
            # for coord in zone.coords:
            #     if self.distance_from_edge[coord] > 0:
            #         self.bot.client.debug_text_3d(f"{self.distance_from_edge[coord]}\n{coord}", self.convert_point2_to_3(Point2(coord)), color)
            #     else:
            #         self.bot.client.debug_text_3d(f"{self.distance_from_edge[coord]}\n{coord}", self.convert_point2_to_3(Point2(coord)), color, size=6)
            if zone.midpoint3:
                self.bot.client.debug_box2_out(zone.midpoint3, 0.25, color)
                self.bot.client.debug_text_3d(f"{zone.midpoint}:{zone_id}", zone.midpoint3)

                for a_midpoint3 in zone.all_midpoints3:
                    self.bot.client.debug_box2_out(a_midpoint3, 0.15, color)

                # for point3 in zone.points_for_drawing.values():
                #     self.bot.client.debug_line_out(zone.midpoint3, point3, color)
                for adjacent_zone in zone.adjacent_zones:
                    if adjacent_zone.midpoint3:
                        self.bot.client.debug_line_out(zone.midpoint3, adjacent_zone.midpoint3, color)

                # path: Path
                # for zone_id in zone.shortest_paths:
                #     path = zone.shortest_paths[zone_id]
                #     if len(path.zones) == 2:
                #         path_point3: Point3 = self.convert_point2_to_3(path.zones[1].midpoint)
                #         color = (255, 255, 0) if path.is_shortest else (255, 255, 255)
                #         self.bot.client.debug_line_out(zone.midpoint3, path_point3, color)
                #         self.bot.client.debug_text_3d(f"{zone_id}", path_point3)
