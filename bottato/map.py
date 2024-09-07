from __future__ import annotations
from typing import List, Dict, Set

from loguru import logger

from sc2.bot_ai import BotAI
from sc2.pixel_map import PixelMap
from sc2.position import Point2, Point3

from .mixins import TimerMixin, GeometryMixin


class Path:
    def __init__(self, zones: List[Zone], distance: float, is_shortest: bool = True) -> None:
        self.distance: float = distance
        self.zones: List[Zone] = zones
        self.is_shortest: bool = is_shortest
        if self.zones is None:
            logger.debug("SELF.ZONES IS NONE")

    def __repr__(self) -> str:
        return f"Path({self.zones}, {self.distance})"

    def add_to_start(self, zone: Zone, distance: float) -> Path:
        new_zones = [zone]
        new_zones.extend(self.zones)
        return Path(new_zones, self.distance + distance)

    def copy(self) -> Path:
        return Path(self.zones.copy(), self.distance)

    def extend(self, path: Path) -> Path:
        self.zones.extend(path.zones[1:])
        self.distance += path.distance
        return self

    def get_reverse(self) -> Path:
        return Path([z for z in reversed(self.zones)], self.distance)


class Zone:
    def __init__(self, id: int, midpoint: tuple, radius: float) -> None:
        self.id: int = id
        self.midpoint: Point2 = Point2(midpoint)
        self.all_midpoints: List[Point2] = [self.midpoint]
        self.radius: float = radius
        self.coords: List[tuple] = [midpoint]
        self.adjacent_zones: Set[Zone] = set()
        self.unchecked_points: List[tuple] = [midpoint]
        # cache routes that have been found
        self.shortest_paths: Dict[int, Path] = {}
        # longer paths should be sorted by distance and not have dupes
        self.longer_paths: Dict[int, List[Path]] = {}
        self.points_for_drawing: Dict[tuple, Point3] = {}
        self.midpoint3: Point3 = None
        self.all_midpoints3: List[Point3] = []
        logger.debug(f"creating zone {id} from {midpoint}")

    def __repr__(self) -> str:
        return f"Zone({self.id}, {self.midpoint}, {self.radius})"

    def add_adjacent_zone(self, zone: Zone):
        adjacent_zone: Zone
        for adjacent_zone in self.adjacent_zones:
            if zone.id == adjacent_zone.id:
                # already added
                break
        else:
            logger.debug(f"adding adjacent zone {zone.id}{zone.midpoint} to {self.id}")
            self.adjacent_zones.add(zone)
            zone.adjacent_zones.add(self)

    def remove_adjacent_zone(self, zone: Zone) -> None:
        if zone in self.adjacent_zones:
            self.adjacent_zones.remove(zone)

    # change to breadth first, drop recursion, instead track unvisited in layers the way build_zones does
    def path_to(self, destination_zone: Zone) -> Path:
        destination_path: Path = Path([], 9999, False)
        logger.debug(f"checking {self} for path to {destination_zone}")
        if destination_zone.id in self.shortest_paths:
            destination_path = self.shortest_paths[destination_zone.id]
        if destination_path.is_shortest:
            logger.debug(f"cached shortest route found {destination_path}")
        else:
            # find shortest route between zones
            unchecked_paths = [Path([self], 0)]

            while unchecked_paths:
                current_path: Path = unchecked_paths.pop(0)
                logger.debug(f"checking path {current_path}")
                if current_path.distance >= destination_path.distance:
                    # this path can't be shorter than the known route, don't continue
                    continue
                last_zone = current_path.zones[-1]
                if last_zone.id in self.shortest_paths and self.shortest_paths[last_zone.id] != current_path:
                    # path has been replaced with a shorter path, skip this one
                    continue

                for adjacent_zone in last_zone.adjacent_zones:
                    logger.debug(f"checking adjacent zone {adjacent_zone}")
                    if adjacent_zone in current_path.zones:
                        # prevent cycles
                        continue
                    if adjacent_zone.id not in last_zone.shortest_paths:
                        new_path = last_zone.add_path_to_adjacent(adjacent_zone)
                        logger.debug(f"adding new adjacent path {new_path}")

                        last_zone.shortest_paths[adjacent_zone.id] = new_path
                        adjacent_zone.shortest_paths[last_zone.id] = new_path.get_reverse()

                        if adjacent_zone.id == destination_zone.id and new_path.distance < destination_path.distance:
                            destination_path = new_path
                            logger.debug(f"shorter path found, adding route from {self} to {destination_zone}: {destination_path}")

                    adjacent_path: Path = last_zone.shortest_paths[adjacent_zone.id]
                    new_full_path: Path = current_path.copy().extend(adjacent_path)
                    new_full_path.is_shortest = False
                    if self.add_path_to_nonadjacent(adjacent_zone, new_full_path):
                        logger.debug(f"adding path to check {new_full_path}")
                        unchecked_paths.append(new_full_path)

                    if adjacent_zone.id == destination_zone.id and new_full_path.distance < destination_path.distance:
                        destination_path = new_full_path
                        logger.debug(f"shorter path found, adding route from {self} to {destination_zone}: {destination_path}")

            logger.debug(f"shortest route: {destination_path}")
            destination_path.is_shortest = True
            # set reverse to be shortest too
            if destination_path.distance < 9999:
                destination_path.zones[-1].shortest_paths[destination_path.zones[0].id].is_shortest = True
        return destination_path

    def add_path_to_adjacent(self, zone: Zone) -> Path:
        distance: float = zone.midpoint.distance_to(self.midpoint)
        new_path = Path([self, zone], distance)
        self.shortest_paths[zone.id] = new_path
        zone.shortest_paths[self.id] = new_path.get_reverse()
        return new_path

    def add_path_to_nonadjacent(self, zone: Zone, path: Path) -> bool:
        is_shorter: bool = False
        try:
            existing_path: Path = self.shortest_paths[zone.id]
            if existing_path.distance >= path.distance:
                is_shorter = True
                self.shortest_paths[zone.id] = path
                zone.shortest_paths[self.id] = path.get_reverse()
                self.add_longer_path(zone, existing_path)
            else:
                self.add_longer_path(zone, path)
        except KeyError:
            is_shorter = True
            self.shortest_paths[zone.id] = path
            zone.shortest_paths[self.id] = path.get_reverse()
        return is_shorter

    def add_longer_path(self, zone: Zone, path: Path):
        if zone.id in self.longer_paths:
            existing_paths = self.longer_paths[zone.id]
            for i in range(len(existing_paths)):
                existing_path = existing_paths[i]
                if existing_path.distance == path.distance:
                    # assume duplicate if distance is the same. could compare paths
                    break
                elif existing_path.distance > path.distance:
                    existing_paths.insert(i, path)
                    break
            else:
                existing_paths.append(path)
        else:
            self.longer_paths[zone.id] = [path]

    def merge_with(self, zone: Zone) -> None:
        self.all_midpoints.append(zone.midpoint)
        self.coords.extend(zone.coords)
        for adjacent in zone.adjacent_zones:
            if adjacent.id != self.id:
                self.adjacent_zones.add(adjacent)
                adjacent.adjacent_zones.add(self)
                adjacent.remove_adjacent_zone(zone)
        zone.unchecked_points = []


class Map(TimerMixin, GeometryMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.zone_lookup_by_coord: Dict[tuple, Zone] = {}
        self.cached_neighbors8: Dict[tuple, set[tuple]] = {}
        self.cached_neighbors4: Dict[tuple, set[tuple]] = {}
        self.coords_by_distance: Dict[int, List[tuple]] = {}
        self.start_timer("init_distance_from_edge")
        self.distance_from_edge: Dict[tuple, int] = self.init_distance_from_edge(self.bot.game_info.pathing_grid)
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

    def init_distance_from_edge(self, pathing_grid: PixelMap) -> Dict[tuple, int]:
        distance_from_edge: Dict[tuple, int] = {}
        # init array with unpathable and put 9999 placeholder for other spots
        previous_layer = []
        next_layer = []
        self.start_timer("init distance 0")
        for x in range(pathing_grid.width):
            for y in range(pathing_grid.height):
                coords = (x, y)
                point = Point2(coords)
                if pathing_grid[point] == 0:
                    next_layer.append(coords)
                    distance_from_edge[coords] = 0
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
                    if neighbor not in distance_from_edge:
                        distance_from_edge[neighbor] = current_distance
                        if not self.has_higher_neighbor(neighbor, distance_from_edge):
                            self.coords_by_distance[current_distance].append(neighbor)
                        # logger.debug(f"distance_from_edge {neighbor} is {distance_from_edge[neighbor]}")
                        next_layer.append(neighbor)

        return distance_from_edge

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
        point2_path: List[Point2] = []
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
                for zone in path.zones:
                    point2_path.append(zone.midpoint)
        return point2_path

    def draw(self) -> None:
        return
        # if self.first_draw:
        #     self.first_draw = False
        #     for zone_id in self.zones:
        #         zone = self.zones[zone_id]
        #         for coords in zone.coords:
        #             zone.points_for_drawing[coords] = self.convert_point2_to_3(Point2(coords))
        #         zone.midpoint3 = self.convert_point2_to_3(zone.midpoint)
        #         for midpoint in zone.all_midpoints:
        #             zone.all_midpoints3.append(self.convert_point2_to_3(midpoint))

        # for coord in self.distance_from_edge:
        #     if self.distance_from_edge[coord] > 0:
        #         self.bot.client.debug_text_3d(f"{self.distance_from_edge[coord]}\n{coord}", self.convert_point2_to_3(Point2(coord)))

        # for zone_id in self.zones:
        #     zone = self.zones[zone_id]
        #     color = (zone.id % 255, (128 + zone.id) % 255, abs(255 - zone.id) % 255)
        #     self.bot.client.debug_box2_out(zone.midpoint3, 0.25, color)
        #     self.bot.client.debug_text_3d(f"{zone.midpoint}:{zone.radius}", zone.midpoint3)

        #     for a_midpoint3 in zone.all_midpoints3:
        #         self.bot.client.debug_box2_out(a_midpoint3, 0.15, color)

        #     for point3 in zone.points_for_drawing.values():
        #         self.bot.client.debug_line_out(zone.midpoint3, point3, color)

        #     path: Path
        #     for zone_id in zone.shortest_paths:
        #         path = zone.shortest_paths[zone_id]
        #         if len(path.zones) == 2:
        #             path_point3: Point3 = self.convert_point2_to_3(path.zones[1].midpoint)
        #             color = (255, 255, 0) if path.is_shortest else (255, 255, 255)
        #             self.bot.client.debug_line_out(zone.midpoint3, path_point3, color)
        #             self.bot.client.debug_text_3d(f"{zone_id}", path_point3)
