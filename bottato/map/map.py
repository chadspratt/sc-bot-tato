from __future__ import annotations
from typing import List, Dict

from loguru import logger
import numpy

from sc2.bot_ai import BotAI
from sc2.pixel_map import PixelMap
from sc2.position import Point2, Point3

from ..mixins import TimerMixin, GeometryMixin
from .zone import Path, Zone
from .influence_maps import InfluenceMaps


class Map(TimerMixin, GeometryMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.influence_maps = InfluenceMaps(self.bot)
        self.zone_lookup_by_coord: Dict[tuple, Zone] = {}
        self.cached_neighbors8: Dict[tuple, set[tuple]] = {}
        self.cached_neighbors4: Dict[tuple, set[tuple]] = {}
        self.coords_by_distance: Dict[int, List[tuple]] = {}
        self.start_timer("init_distance_from_edge")
        self.init_distance_from_edge(self.bot.game_info.pathing_grid)
        self.stop_timer("init_distance_from_edge")
        # self.start_timer("init_open_area_midpoints")
        # self.open_area_midpoints: List[tuple] = self.init_open_area_midpoints(self.distance_from_edge)
        # self.stop_timer("init_open_area_midpoints")
        # logger.debug(f"open_area_midpoints {self.open_area_midpoints}")
        self.start_timer("init_zones")
        self.zones: Dict[int, Zone] = self.init_zones(self.distance_from_edge)
        self.stop_timer("init_zones")
        logger.debug(f"zones {self.zones}")
        self.first_draw = True

    def init_distance_from_edge(self, pathing_grid: PixelMap):
        self.distance_from_edge: Dict[tuple, int] = {}
        # init array with unpathable and put 9999 placeholder for other spots
        previous_layer = []
        next_layer = []
        unpathable = []

        self.start_timer("init distance 0")
        for x in range(pathing_grid.width):
            for y in range(pathing_grid.height):
                coords = (x, y)
                point = Point2(coords)
                if pathing_grid[point] == 0:
                    next_layer.append(coords)
                    unpathable.append(coords)
                    self.distance_from_edge[coords] = 0
        self.stop_timer("init distance 0")

        current_distance = 0
        while next_layer:
            previous_layer = next_layer
            current_distance += 1
            self.coords_by_distance[current_distance] = []
            next_layer = []
            # logger.debug(f"current layer {previous_layer}")
            for previous_coord in previous_layer:
                neighbors = self.neighbors4(previous_coord)
                for neighbor in neighbors:
                    # logger.debug(f"neighbor of {previous_coord}: {neighbor}")
                    if neighbor not in self.distance_from_edge:
                        self.distance_from_edge[neighbor] = current_distance
                        if not self.has_higher_neighbor(neighbor, self.distance_from_edge):
                            self.coords_by_distance[current_distance].append(neighbor)
                        # logger.debug(f"self.distance_from_edge {neighbor} is {self.distance_from_edge[neighbor]}")
                        next_layer.append(neighbor)

    def neighbors8(self, coords: tuple) -> list:
        if coords not in self.cached_neighbors8:
            coord_height = self.bot.get_terrain_z_height(Point2(coords))
            max_x = self.bot.game_info.pathing_grid.width - 1
            max_y = self.bot.game_info.pathing_grid.height - 1
            neighbors: list[tuple] = []
            self.cached_neighbors8[coords] = neighbors
            if coords[0] > 0:
                if coords[1] > 0:
                    self.add_if_similar_height((coords[0] - 1, coords[1] - 1), coord_height, neighbors)
                self.add_if_similar_height((coords[0] - 1, coords[1]), coord_height, neighbors)
                if coords[1] < max_y:
                    self.add_if_similar_height((coords[0] - 1, coords[1] + 1), coord_height, neighbors)
            if coords[1] > 0:
                self.add_if_similar_height((coords[0], coords[1] - 1), coord_height, neighbors)
            if coords[1] < max_y:
                self.add_if_similar_height((coords[0], coords[1] + 1), coord_height, neighbors)
            if coords[0] < max_x:
                if coords[1] > 0:
                    self.add_if_similar_height((coords[0] + 1, coords[1] - 1), coord_height, neighbors)
                self.add_if_similar_height((coords[0] + 1, coords[1]), coord_height, neighbors)
                if coords[1] < max_y:
                    self.add_if_similar_height((coords[0] + 1, coords[1] + 1), coord_height, neighbors)
        return self.cached_neighbors8[coords]

    def neighbors4(self, coords) -> list:
        if coords not in self.cached_neighbors4:
            max_x = self.bot.game_info.pathing_grid.width - 1
            max_y = self.bot.game_info.pathing_grid.height - 1
            neighbors: list[tuple] = []
            self.cached_neighbors4[coords] = neighbors
            if coords[0] > 0:
                neighbors.append((coords[0] - 1, coords[1]))
            if coords[1] > 0:
                neighbors.append((coords[0], coords[1] - 1))
            if coords[1] < max_y:
                neighbors.append((coords[0], coords[1] + 1))
            if coords[0] < max_x:
                neighbors.append((coords[0] + 1, coords[1]))
        return self.cached_neighbors4[coords]

    def add_if_similar_height(self, coords, height, neighbors: list[tuple]):
        neighbor_height = self.bot.get_terrain_z_height(Point2(coords))
        if abs(height - neighbor_height) < 0.5:
            neighbors.append(coords)

    def has_higher_neighbor(self, coords: tuple, distance_from_edge) -> bool:
        distance = distance_from_edge[coords]
        for neighbor in self.neighbors8(coords):
            if neighbor in distance_from_edge and distance_from_edge[neighbor] > distance:
                return True
        return False

    def init_zones(self, distance_from_edge: Dict[tuple, int]) -> Dict[int, Zone]:
        coords: tuple
        zone_index = 0
        zones: Dict[int, Zone] = {}
        distances: List[int] = sorted(self.coords_by_distance, reverse=True)
        zones_to_remove = []
        logger.debug(f"distances {distances}")
        for distance in distances:
            zone: Zone
            for zone in zones.values():
                points_to_check: List[tuple] = zone.unchecked_points
                zone.unchecked_points = []
                while points_to_check:
                    next_point = points_to_check.pop()
                    current_distance_to_edge = distance_from_edge[next_point]
                    neighbors = self.neighbors8(next_point)
                    neighbor: tuple
                    # expand to any neighbors that are closer to the edge (won't push in to next zone)
                    if next_point in [(37, 89), (38, 89), (39, 89)]:
                        logger.debug(f"{next_point} distance {current_distance_to_edge} neighbors {neighbors}")
                    for neighbor in neighbors:
                        try:
                            point_zone = self.zone_lookup_by_coord[neighbor]
                            if point_zone.id == zone.id:
                                pass
                                # skip duplicates in same zone
                                # if next_point in [(37, 89), (38, 89), (39, 89)]:
                                #     logger.debug(f"neighbor already in zone {neighbor}")
                            elif point_zone.radius == zone.radius and current_distance_to_edge >= zone.radius - 1:
                                # merge zones
                                # if next_point in [(37, 89), (38, 89), (39, 89)]:
                                #     logger.debug(f"merging zone {point_zone} in to {zone}")
                                for coords in point_zone.coords:
                                    self.zone_lookup_by_coord[coords] = zone
                                points_to_check.extend(point_zone.unchecked_points)
                                zones_to_remove.append(point_zone)
                                zone.merge_with(point_zone)
                            elif distance_from_edge[neighbor] > 0:
                                # if next_point in [(37, 89), (38, 89), (39, 89)]:
                                #     logger.debug(f"neighbor in adjacent zone {neighbor}")
                                zone.add_adjacent_zone(point_zone)
                        except KeyError:
                            # unassigned point, check if closer to edge
                            neighbor_distance = distance_from_edge[neighbor]
                            # match lower points or equal height
                            if (neighbor_distance <= current_distance_to_edge):
                                # if next_point in [(37, 89), (38, 89), (39, 89)]:
                                #     logger.debug(f"{neighbor} adding to zone {zone.id}")
                                self.zone_lookup_by_coord[neighbor] = zone
                                zone.coords.append(neighbor)
                                zone.unchecked_points.append(neighbor)

            if distance > 1:
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

        for removed_zone in zones_to_remove:
            # zone = zones[removed_zone_id]
            del zones[removed_zone.id]
            for zone in zones.values():
                zone.remove_adjacent_zone(removed_zone)
                if removed_zone in zone.adjacent_zones:
                    zone.adjacent_zones.remove(removed_zone)

        for zone in zones.values():
            all_point2s = [Point2(coord) for coord in zone.coords]
            zone.midpoint = Point2.center(all_point2s)

        logger.debug(f"all zones ({len(zones)}){zones}")
        return zones

    def get_path(self, start: Point2, end: Point2) -> List[Point2]:
        point2_path: List[Point2] = [start]
        start_rounded: Point2 = start.rounded
        end_rounded: Point2 = end.rounded
        try:
            start_zone = self.zone_lookup_by_coord[(start_rounded.x, start_rounded.y)]
            end_zone = self.zone_lookup_by_coord[(end_rounded.x, end_rounded.y)]
        except KeyError:
            return point2_path
        logger.debug(f"start_zone {start_zone}")
        logger.debug(f"end_zone {end_zone}")
        if start_zone.id != end_zone.id:
            zone: Zone
            path: Path = start_zone.path_to(end_zone)
            if path:
                logger.debug(f"found path {path}")
                for zone in path.zones[1:-1]:
                    point2_path.append(zone.midpoint)
                point2_path.append(end)
        return point2_path

    def get_pathable_position(self, position: Point2) -> Point2:
        rounded_position = position.rounded
        if self.ground_grid[rounded_position.x, rounded_position.y] != numpy.inf:
            return position
        return self.influence_maps.closest_towards_point(self.influence_maps.find_lowest_cost_points(position, 3, self.ground_grid), position)
        # pathing_grid = self.bot.game_info.pathing_grid
        # pathable_ground = position
        # if pathing_grid[position] == 0:
        #     if position not in self.nearest_ground:
        #         self.nearest_ground[position]
        #     pathable_ground = self.nearest_ground[position]
        # return pathable_ground

    def update_influence_maps(self) -> None:
        self.ground_grid = self.influence_maps.get_pyastar_grid()

    def draw(self) -> None:
        if self.first_draw:
            self.first_draw = False
            for zone_id in self.zones:
                zone = self.zones[zone_id]
                for coords in zone.coords:
                    zone.points_for_drawing[coords] = self.convert_point2_to_3(Point2(coords))
                zone.midpoint3 = self.convert_point2_to_3(zone.midpoint)
                for midpoint in zone.all_midpoints:
                    zone.all_midpoints3.append(self.convert_point2_to_3(midpoint))

        for coord in self.distance_from_edge:
            if self.distance_from_edge[coord] > 0:
                self.bot.client.debug_text_3d(f"{self.distance_from_edge[coord]}\n{coord}", self.convert_point2_to_3(Point2(coord)))

        for zone_id in self.zones:
            zone = self.zones[zone_id]
            color = (zone.id % 255, (128 + zone.id) % 255, abs(255 - zone.id) % 255)
            self.bot.client.debug_box2_out(zone.midpoint3, 0.25, color)
            self.bot.client.debug_text_3d(f"{zone.midpoint}:{zone.radius}", zone.midpoint3)

            for a_midpoint3 in zone.all_midpoints3:
                self.bot.client.debug_box2_out(a_midpoint3, 0.15, color)

            for point3 in zone.points_for_drawing.values():
                self.bot.client.debug_line_out(zone.midpoint3, point3, color)

            path: Path
            for zone_id in zone.shortest_paths:
                path = zone.shortest_paths[zone_id]
                if len(path.zones) == 2:
                    path_point3: Point3 = self.convert_point2_to_3(path.zones[1].midpoint)
                    color = (255, 255, 0) if path.is_shortest else (255, 255, 255)
                    self.bot.client.debug_line_out(zone.midpoint3, path_point3, color)
                    self.bot.client.debug_text_3d(f"{zone_id}", path_point3)
