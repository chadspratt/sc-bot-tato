from itertools import chain
from typing import List, Optional, Tuple

from sc2.unit import Unit
from sc2.position import Point2, Point3
from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI

from bottato.map.utils import change_destructible_status_in_grid
from bottato.map.destructibles import BUILDINGS

from loguru import logger
import numpy as np
from scipy.spatial import distance


class InfluenceMaps():
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.maps = {}
        self.map_name: str = bot.game_info.map_name
        self.path_arr: np.ndarray = self.bot.game_info.pathing_grid.data_numpy
        self.placement_arr: np.ndarray = self.bot.game_info.placement_grid.data_numpy

        # need to consider the placement arr because our base minerals, geysers and townhall
        # are not pathable in the pathing grid
        # we manage those manually so they are accurate through the game
        self.default_grid = np.fmax(self.path_arr, self.placement_arr).T

        # Fixing platforms on Submarine which reapers can climb onto not being pathable
        # Don't use the entire name because we also use the modified maps
        # with different names
        if "Submarine" in self.map_name:
            self.default_grid[116, 43] = 1
            self.default_grid[51, 120] = 1

        self.default_grid_nodestr = self.default_grid.copy()
        self.long_range_grid = self.default_grid.copy()

        self.destructables_included = {}
        self.minerals_included = {}
        self.watchtowers_included = {}

        # set rocks and mineral walls to pathable in the beginning
        # these will be set nonpathable when updating grids for the destructables
        # that still exist
        for dest in self.bot.destructables:
            self.destructables_included[dest.position] = dest
            if "unbuildable" not in dest.name.lower() and "acceleration" not in dest.name.lower():
                change_destructible_status_in_grid(self.default_grid, dest, 0)
                change_destructible_status_in_grid(self.default_grid_nodestr, dest, 1)
                change_destructible_status_in_grid(self.long_range_grid, dest, 0)

        # set each geyser as non pathable, these don't update during the game
        for geyser in self.bot.vespene_geyser:
            left_bottom = geyser.position.offset(Point2((-1.5, -1.5)))
            x_start = int(left_bottom[0])
            y_start = int(left_bottom[1])
            x_end = int(x_start + 3)
            y_end = int(y_start + 3)
            self.default_grid[x_start:x_end, y_start:y_end] = 0
            self.default_grid_nodestr[x_start:x_end, y_start:y_end] = 0

        for mineral in self.bot.mineral_field:
            self.minerals_included[mineral.position] = mineral
            x1 = int(mineral.position[0])
            x2 = x1 - 1
            y = int(mineral.position[1])

            self.default_grid[x1, y] = 0
            self.default_grid[x2, y] = 0
            self.default_grid_nodestr[x1, y] = 0
            self.default_grid_nodestr[x2, y] = 0
            if mineral.type_id == UnitTypeId.RICHMINERALFIELD:
                self.long_range_grid[x1, y] = 0
                self.long_range_grid[x2, y] = 0

        for watchtower in self.bot.watchtowers:
            self.watchtowers_included[watchtower.position] = watchtower
            left_bottom = watchtower.position.offset(Point2((-1, -1)))
            x_start = int(left_bottom[0])
            y_start = int(left_bottom[1])
            x_end = int(x_start + 2)
            y_end = int(y_start + 2)
            self.default_grid[x_start:x_end, y_start:y_end] = 0
            self.default_grid_nodestr[x_start:x_end, y_start:y_end] = 0
            self.long_range_grid[x_start:x_end, y_start:y_end] = 0

    def get_base_pathing_grid(self, include_destructibles: bool = True):
        if include_destructibles:
            return self.default_grid.copy()
        else:
            return self.default_grid_nodestr.copy()

    def get_clean_air_grid(self, default_weight: float = 1) -> np.ndarray:
        clean_air_grid = np.zeros(shape=self.default_grid.shape).astype(np.float32)
        area = self.bot.game_info.playable_area
        clean_air_grid[area.x:(area.x + area.width), area.y:(area.y + area.height)] = 1
        return np.where(clean_air_grid == 1, default_weight, np.inf).astype(np.float32)

    def get_pyastar_grid(self, default_weight: float = 1, include_destructables: bool = True) -> np.ndarray:
        grid = self.get_base_pathing_grid(include_destructables)
        grid = self._add_non_pathables_ground(grid=grid, include_destructables=include_destructables)

        grid = np.where(grid != 0, default_weight, np.inf).astype(np.float32)
        return grid
    
    def get_long_range_grid(self) -> np.ndarray:
        grid = self.long_range_grid.copy()
        grid = self._add_non_pathables_ground(grid=grid, include_destructables=True)
        return grid

    def add_building_to_grid(self, type_id: UnitTypeId, position: Point2, grid: np.ndarray, weight=0):
        size = 1
        if type_id in BUILDINGS["2x2"]:
            size = 2
        elif type_id in BUILDINGS["3x3"]:
            size = 3
        elif type_id in BUILDINGS["5x5"]:
            size = 5
        left_bottom = position.offset(Point2((-size / 2, -size / 2)))
        x_start = int(left_bottom[0])
        y_start = int(left_bottom[1])
        x_end = int(x_start + size)
        y_end = int(y_start + size)

        grid[x_start:x_end, y_start:y_end] = weight

        # townhall sized buildings should have their corner spots pathable
        if size == 5:
            grid[x_start, y_start] = 1
            grid[x_start, y_end - 1] = 1
            grid[x_end - 1, y_start] = 1
            grid[x_end - 1, y_end - 1] = 1

    def _add_non_pathables_ground(self, grid: np.ndarray, include_destructables: bool = True) -> np.ndarray:
        ret_grid = grid.copy()
        nonpathables = self.bot.structures.not_flying
        nonpathables.extend(self.bot.enemy_structures.not_flying)
        nonpathables = nonpathables.filter(
            lambda x: (
                x.type_id != UnitTypeId.SUPPLYDEPOTLOWERED or x.is_active
            ) and (
                x.type_id != UnitTypeId.CREEPTUMOR or not x.is_ready
            )
        )

        for structure in nonpathables:
            self.add_building_to_grid(structure.type_id, structure.position, ret_grid)

        if len(self.minerals_included) != self.bot.mineral_field.amount:
            new_positions = set(m.position for m in self.bot.mineral_field)
            old_mf_positions = set(self.minerals_included)

            missing_positions = old_mf_positions - new_positions
            for mf_position in missing_positions:
                x1 = int(mf_position[0])
                x2 = x1 - 1
                y = int(mf_position[1])

                ret_grid[x1, y] = 1
                ret_grid[x2, y] = 1

                self.default_grid[x1, y] = 1
                self.default_grid[x2, y] = 1

                self.default_grid_nodestr[x1, y] = 1
                self.default_grid_nodestr[x2, y] = 1

                self.long_range_grid[x1, y] = 1
                self.long_range_grid[x2, y] = 1

                del self.minerals_included[mf_position]

        if include_destructables and len(self.destructables_included) != self.bot.destructables.amount:
            new_positions = set(d.position for d in self.bot.destructables)
            old_dest_positions = set(self.destructables_included)
            missing_positions = old_dest_positions - new_positions

            for dest_position in missing_positions:
                dest = self.destructables_included[dest_position]
                change_destructible_status_in_grid(ret_grid, dest, 1)
                change_destructible_status_in_grid(self.default_grid, dest, 1)
                change_destructible_status_in_grid(self.long_range_grid, dest, 1)

                del self.destructables_included[dest_position]

        if len(self.watchtowers_included) != self.bot.watchtowers.amount:
            new_positions = set(w.position for w in self.bot.watchtowers)
            old_watchtower_positions = set(self.watchtowers_included)
            missing_positions = old_watchtower_positions - new_positions

            for watchtower_position in missing_positions:
                left_bottom = watchtower_position.offset((-1, -1))
                x_start = int(left_bottom[0])
                y_start = int(left_bottom[1])
                x_end = int(x_start + 2)
                y_end = int(y_start + 2)
                ret_grid[x_start:x_end, y_start:y_end] = 1
                self.default_grid[x_start:x_end, y_start:y_end] = 1
                self.long_range_grid[x_start:x_end, y_start:y_end] = 1

                del self.watchtowers_included[watchtower_position]

        return ret_grid
    
    def destructables_changed(self) -> bool:
        if len(self.destructables_included) != self.bot.destructables.amount:
            # check that the changed destructable wasn't just an unbuildable
            new_positions = set(d.position for d in self.bot.destructables)
            old_dest_positions = set(self.destructables_included)
            missing_positions = old_dest_positions - new_positions
            missing_destructables = [self.destructables_included[pos] for pos in missing_positions]
            for dest in missing_destructables:
                if "unbuildable" not in dest.name.lower() and "acceleration" not in dest.name.lower():
                    return True
        return False

    def _bounded_circle(self, center, radius, shape):
        xx, yy = np.ogrid[:shape[0], :shape[1]]
        circle = (xx - center[0]) ** 2 + (yy - center[1]) ** 2
        return np.nonzero(circle <= radius ** 2)

    def draw_circle(self, c, radius, shape=None):
        center = np.array(c)
        upper_left = np.ceil(center - radius).astype(int)
        lower_right = np.floor(center + radius).astype(int) + 1

        if shape is not None:
            # Constrain upper_left and lower_right by shape boundary.
            upper_left = np.maximum(upper_left, 0)
            lower_right = np.minimum(lower_right, np.array(shape))

        shifted_center = center - upper_left
        bounding_shape = lower_right - upper_left

        rr, cc = self._bounded_circle(shifted_center, radius, bounding_shape)
        return rr + upper_left[0], cc + upper_left[1]

    def lowest_cost_points_array(self, from_pos: tuple, radius: float, grid: np.ndarray) -> Optional[np.ndarray]:
        """For use with evaluations that use numpy arrays
                example: # Closest point to unit furthest from target
                        distances = cdist([[unitpos, targetpos]], lowest_points, "sqeuclidean")
                        lowest_points[(distances[0] - distances[1]).argmin()]
            - 140 µs per loop
        """

        disk = tuple(self.draw_circle(from_pos, radius, shape=grid.shape))
        if len(disk[0]) == 0:
            return None

        arrmin = np.min(grid[disk])
        cond = grid[disk] == arrmin
        return np.column_stack((disk[0][cond], disk[1][cond]))

    def find_lowest_cost_points(self, from_pos: Point2, radius: float, grid: np.ndarray) -> Optional[List[Point2]]:
        lowest = self.lowest_cost_points_array(from_pos, radius, grid)

        if lowest is None:
            return None

        return list(map(Point2, lowest))

    @staticmethod
    def closest_node_idx(
            node: Point2 | np.ndarray, nodes: List[tuple[int, int]] | np.ndarray | List[Point2]
    ) -> int:
        """
        :rtype: int

        Given a list of ``nodes``  and a single ``node`` ,

        will return the index of the closest node in the list to ``node``

        """
        if isinstance(nodes, list):
            iter = chain.from_iterable(nodes)
            nodes = np.fromiter(iter, dtype=type(nodes[0][0]), count=len(nodes) * 2).reshape((-1, 2))

        closest_index = distance.cdist([node], nodes, "sqeuclidean").argmin() # type: ignore
        return int(closest_index)

    def closest_towards_point(
            self, points: List[Point2], target: Point2 | np.ndarray
    ) -> Point2:
        """
        :rtype: :class:`sc2.position.Point2`

        Given a list/set of points, and a target,

        will return the point that is closest to that target

        Example:
                Calculate a position for tanks in direction to the enemy forces
                passing in the Area's corners as points and enemy army's location as target

                >>> enemy_army_position = (50,50)
                >>> my_base_location = self.bot.townhalls[0].position
                >>> my_region = self.where_all(my_base_location)[0]
                >>> best_siege_spot = self.closest_towards_point(points=my_region.corner_points, target=enemy_army_position)
                >>> best_siege_spot
                (49, 52)

        """

        if not isinstance(points, (list, np.ndarray)):
            logger.warning(type(points))

        return points[self.closest_node_idx(node=target, nodes=points)]

    def set_position_unpathable(self, position: Point2, grid: np.ndarray, unit: Unit):
        self.add_cost(position, unit.radius, grid, np.inf) # type: ignore

    def add_cost(self, position: Tuple[float, float], radius: float, grid: np.ndarray, weight: float = 100,
                 safe: bool = True,
                 initial_default_weights: float = 0) -> np.ndarray:
        """
        :rtype: numpy.ndarray

        Will add cost to a `circle-shaped` area with a center ``position`` and radius ``radius``

        weight of 100

        Warning:
            When ``safe=False`` the Pather will not adjust illegal values below 1 which could result in a crash`

        See Also:
            * :meth:`.MapData.add_cost_to_multiple_grids`

        """
        disk = tuple(self.draw_circle(position, radius, grid.shape))

        arr: np.ndarray = self._add_disk_to_grid(
            position, grid, disk, weight, safe, initial_default_weights
        )

        return arr

    @staticmethod
    def _add_disk_to_grid(
        position: Tuple[float, float],
        arr: np.ndarray,
        disk: Tuple,
        weight: float = 100,
        safe: bool = True,
        initial_default_weights: float = 0,
    ) -> np.ndarray:
        # if we don't touch any cell origins due to a small radius, add at least the cell
        # the given position is in
        if (
            len(disk[0]) == 0
            and 0 <= position[0] < arr.shape[0]
            and 0 <= position[1] < arr.shape[1]
        ):
            disk = (int(position[0]), int(position[1]))

        if initial_default_weights > 0:
            arr[disk] = np.where(arr[disk] == 1, initial_default_weights, arr[disk])

        arr[disk] += weight
        if safe and np.any(arr[disk] < 1):
            logger.warning(
                "You are attempting to set weights that are below 1. falling back to the minimum (1)"
            )
            arr[disk] = np.where(arr[disk] < 1, 1, arr[disk])

        return arr

    def draw_influence_in_game(self, grid: np.ndarray,
                               lower_threshold: int = 1,
                               upper_threshold: int = 1000,
                               color: Tuple[int, int, int] = (201, 168, 79),
                               size: int = 13) -> None:
        """
        :rtype: None
        Draws influence (cost) values of a grid in game.

        Caution:
            Setting the lower threshold too low impacts performance since almost every value will get drawn.

            It's recommended that this is set to the relevant grid's default weight value.

        Example:
                >>> self.ground_grid = self.get_pyastar_grid(default_weight=1)
                >>> self.ground_grid = self.add_cost((100, 100), radius=15, grid=self.ground_grid, weight=50)
                >>> # self.draw_influence_in_game(self.ground_grid, lower_threshold=1) # commented out for doctest

        See Also:
            * :meth:`.MapData.get_pyastar_grid`
            * :meth:`.MapData.get_climber_grid`
            * :meth:`.MapData.get_clean_air_grid`
            * :meth:`.MapData.get_air_vs_ground_grid`
            * :meth:`.MapData.add_cost`

        """
        height: float = self.bot.get_terrain_z_height(self.bot.start_location)
        for x, y in zip(*np.where((grid > lower_threshold) & (grid <= upper_threshold))):
            pos: Point3 = Point3((x, y, height))
            if grid[x, y] == np.inf:
                val: int = 9999
            else:
                val: int = int(grid[x, y])
            self.bot.client.debug_text_world(str(val), pos, color, size)
