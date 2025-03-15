from itertools import chain
from typing import List, Optional, Tuple, Union

from sc2.position import Point2
from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI

from .utils import change_destructible_status_in_grid
from .destructibles import buildings

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

        self.destructables_included = {}
        self.minerals_included = {}

        # set rocks and mineral walls to pathable in the beginning
        # these will be set nonpathable when updating grids for the destructables
        # that still exist
        for dest in self.bot.destructables:
            self.destructables_included[dest.position] = dest
            if "unbuildable" not in dest.name.lower() and "acceleration" not in dest.name.lower():
                change_destructible_status_in_grid(self.default_grid, dest, 0)
                change_destructible_status_in_grid(self.default_grid_nodestr, dest, 1)

        # set each geyser as non pathable, these don't update during the game
        for geyser in self.bot.vespene_geyser:
            left_bottom = geyser.position.offset((-1.5, -1.5))
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

    def get_base_pathing_grid(self, include_destructibles: bool = True):
        if include_destructibles:
            return self.default_grid.copy()
        else:
            return self.default_grid_nodestr.copy()

    def get_pyastar_grid(self, default_weight: float = 1, include_destructables: bool = True) -> np.ndarray:
        grid = self.get_base_pathing_grid(include_destructables)
        grid = self._add_non_pathables_ground(grid=grid, include_destructables=include_destructables)

        grid = np.where(grid != 0, default_weight, np.inf).astype(np.float32)
        return grid

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

        for obj in nonpathables:
            size = 1
            if obj.type_id in buildings["2x2"]:
                size = 2
            elif obj.type_id in buildings["3x3"]:
                size = 3
            elif obj.type_id in buildings["5x5"]:
                size = 5
            left_bottom = obj.position.offset((-size / 2, -size / 2))
            x_start = int(left_bottom[0])
            y_start = int(left_bottom[1])
            x_end = int(x_start + size)
            y_end = int(y_start + size)

            ret_grid[x_start:x_end, y_start:y_end] = 0

            # townhall sized buildings should have their corner spots pathable
            if size == 5:
                ret_grid[x_start, y_start] = 1
                ret_grid[x_start, y_end - 1] = 1
                ret_grid[x_end - 1, y_start] = 1
                ret_grid[x_end - 1, y_end - 1] = 1

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

                del self.minerals_included[mf_position]

        if include_destructables and len(self.destructables_included) != self.bot.destructables.amount:
            new_positions = set(d.position for d in self.bot.destructables)
            old_dest_positions = set(self.destructables_included)
            missing_positions = old_dest_positions - new_positions

            for dest_position in missing_positions:
                dest = self.destructables_included[dest_position]
                change_destructible_status_in_grid(ret_grid, dest, 1)
                change_destructible_status_in_grid(self.default_grid, dest, 1)

                del self.destructables_included[dest_position]

        return ret_grid

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
            node: Union[Point2, np.ndarray], nodes: Union[List[Tuple[int, int]], np.ndarray]
    ) -> int:
        """
        :rtype: int

        Given a list of ``nodes``  and a single ``node`` ,

        will return the index of the closest node in the list to ``node``

        """
        if isinstance(nodes, list):
            iter = chain.from_iterable(nodes)
            nodes = np.fromiter(iter, dtype=type(nodes[0][0]), count=len(nodes) * 2).reshape((-1, 2))

        closest_index = distance.cdist([node], nodes, "sqeuclidean").argmin()
        return closest_index

    def closest_towards_point(
            self, points: List[Point2], target: Union[Point2, tuple]
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
