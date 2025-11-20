from __future__ import annotations
from typing import List, Dict, Set

from loguru import logger

from sc2.position import Point2, Point3


class Path:
    def __init__(self, zones: List[Zone], distance: float, is_shortest: bool = True) -> None:
        self.distance: float = distance
        self.zones: List[Zone] = zones
        self.is_shortest: bool = is_shortest
        if self.zones is None:
            logger.debug("SELF.ZONES IS NONE")

    def __repr__(self) -> str:
        return f"Path({self.zones}, {self.distance})"
    
    def __ne__(self, other: object) -> bool:
        assert isinstance(other, Path)
        if len(self.zones) != len(other.zones):
            return True
        for i in range(len(self.zones)):
            if self.zones[i].id != other.zones[i].id:
                return True
        return False

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
        self.midpoint3: Point3 | None = None
        self.all_midpoints3: List[Point3] = []
        self.damage_received: List[tuple[float, float]] = []  # (amount, time)
        logger.debug(f"creating zone {id} from {midpoint}")

    def __repr__(self) -> str:
        return f"Zone({self.id}, {self.midpoint}, {self.radius})"
    
    def add_damage(self, amount: float, time: float) -> None:
        self.damage_received.append((amount, time))

    def get_damage_in_last_seconds(self, seconds: float, current_time: float) -> float:
        total_damage = 0.0
        for damage, time in self.damage_received:
            if current_time - time <= seconds:
                total_damage += damage
        return total_damage

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
        if destination_zone.id == self.id:
            # same zone
            return Path([], 0)
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
        is_shorter_or_equal: bool = False
        try:
            existing_path: Path = self.shortest_paths[zone.id]
            existing_distance = round(existing_path.distance, 2)
            new_distance = round(path.distance, 2)
            if existing_distance == new_distance:
                is_shorter_or_equal = True
            elif existing_distance > new_distance:
                is_shorter_or_equal = True
                self.shortest_paths[zone.id] = path
                zone.shortest_paths[self.id] = path.get_reverse()
            else:
                self.add_longer_path(zone, path)
        except KeyError:
            is_shorter_or_equal = True
            self.shortest_paths[zone.id] = path
            zone.shortest_paths[self.id] = path.get_reverse()
        return is_shorter_or_equal

    # unused
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
