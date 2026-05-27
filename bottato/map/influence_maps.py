from itertools import chain
from loguru import logger
from typing import Dict, List, Optional, Tuple

import numpy as np
from cython_extensions.geometry import cy_distance_to
from MapAnalyzer import MapData
from sc2.bot_ai import BotAI
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from scipy.spatial import distance

from bottato.map.destructibles import BUILDINGS
from bottato.map.utils import change_destructible_status_in_grid
from bottato.unit_types import UnitTypes


class InfluenceMaps():
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.maps = {}
        self.map_data = MapData(bot, corner_distance=0)
        self.map_name: str = bot.game_info.map_name

    def update_maps(self, damage_by_position: Dict[Point2, List[Tuple[float, float]]]):
        self.ground_grid = self.map_data.get_pyastar_grid(3)
        self.reaper_grid = self.map_data.get_climber_grid(3)
        self.anti_air_grid = self.map_data.get_air_vs_ground_grid(3, 1.5)
        self.detection_grid = self.map_data.get_clean_air_grid()

        # subtract weight for speed zones
        for destructable in self.bot.destructables:
            position = (destructable.position[0], destructable.position[1])
            if destructable.type_id == UnitTypeId.ACCELERATIONZONESMALL:
                self.add_cost(position, 4, self.ground_grid, -1)
                self.add_cost(position, 4, self.reaper_grid, -1)
                self.add_cost(position, 4, self.anti_air_grid, -1)
            elif destructable.type_id == UnitTypeId.ACCELERATIONZONELARGE:
                self.add_cost(position, 6, self.ground_grid, -1)
                self.add_cost(position, 6, self.reaper_grid, -1)
                self.add_cost(position, 6, self.anti_air_grid, -1)

        cutoff_time = self.bot.time - 10
        for position, damage_list in damage_by_position.items():
            total_damage = 0.0
            for damage, time in damage_list:
                if time < cutoff_time:
                    continue
                total_damage += damage
            if total_damage > 0:
                self.add_cost((position[0], position[1]), 1.5, self.ground_grid, total_damage*10)
                self.add_cost((position[0], position[1]), 1.5, self.reaper_grid, total_damage*10)
        
        for enemy in self.bot.all_enemy_units:
            ground_range = UnitTypes.ground_range(enemy)
            if ground_range > 0 and enemy.is_ready:
                self.add_cost((enemy.position[0], enemy.position[1]), ground_range + 1.5, self.ground_grid)
                self.add_cost((enemy.position[0], enemy.position[1]), ground_range + 1.5, self.reaper_grid)

            air_range = UnitTypes.air_range(enemy)
            if air_range > 0 and enemy.is_ready:
                self.add_cost((enemy.position[0], enemy.position[1]), air_range + 1.5, self.anti_air_grid)

            if enemy.is_detector:
                self.add_cost((enemy.position[0], enemy.position[1]), enemy.sight_range + 1.5, self.detection_grid, 5)

        for effect in self.bot.state.effects:
            if effect.id == EffectId.SCANNERSWEEP:
                for position in effect.positions:
                    self.add_cost((position[0], position[1]), 14, self.detection_grid, 5)

        # cap detection weights at 5x (detection is multiplied with other grid for cloaked units)
        self.detection_grid = np.minimum(self.detection_grid, 5)

    def get_zone_grid(self, include_destructables: bool = True) -> np.ndarray:
        """Grid for zone/topology computation — terrain + destructibles, no player structures.

        Zones represent map terrain topology and should not be fragmented by
        temporary player buildings.  This avoids an exponential slowdown in
        init_zones when many buildings are present (e.g. continue-from-replay).
        """
        grid = self.map_data.pather.long_range_grid.copy()
        grid = self.map_data.pather._add_non_pathables_ground(grid=grid, include_destructables=include_destructables, include_structures=False)
        return grid
    
    def destructables_changed(self) -> bool:
        if len(self.map_data.pather.destructables_included) != self.bot.destructables.amount:
            # check that the changed destructable wasn't just an unbuildable
            new_positions = set(d.position for d in self.bot.destructables)
            old_dest_positions = set(self.map_data.pather.destructables_included)
            missing_positions = old_dest_positions - new_positions
            missing_destructables = [self.map_data.pather.destructables_included[pos] for pos in missing_positions]
            for dest in missing_destructables:
                if "unbuildable" not in dest.name.lower() and "acceleration" not in dest.name.lower():
                    return True
        return False

    def find_lowest_cost_points(self, from_pos: Point2, radius: float, grid: np.ndarray) -> Optional[List[Point2]]:
        return self.map_data.pather.find_lowest_cost_points(from_pos, radius, grid)

    def closest_towards_point(
            self, points: List[Point2], target: Point2 | tuple
    ) -> Point2:
        return self.map_data.closest_towards_point(points, target)

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
        return self.map_data.pather.add_cost(position=position, radius=radius, arr=grid, weight=weight, safe=safe,
                                             initial_default_weights=initial_default_weights)
    
    def get_path(self, start: Point2 | Unit, end: Point2, grid: Optional[np.ndarray] = None) -> List[Point2]:
        if isinstance(start, Unit):
            if start.type_id == UnitTypeId.REAPER:
                grid = self.reaper_grid
            elif start.is_flying:
                grid = self.anti_air_grid
            else:
                grid = self.ground_grid
            if start.is_cloaked:
                grid *= self.detection_grid
            start = start.position
        
        path = self.map_data.pathfind((start.x, start.y), (end.x, end.y), grid=grid)
        if path is None:
            return [start, end]
        return path
    
    def get_path_distance(self, start: Point2, end: Point2, grid: np.ndarray) -> float:
        path = self.get_path(start, end, grid)
        if path is None:
            return float('inf')
        distance = 0
        prev_position = None
        for position in path:
            if prev_position is not None:
                distance += cy_distance_to(prev_position, position)
            prev_position = position
        return distance

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
        self.map_data.draw_influence_in_game(grid=grid,
                                             lower_threshold=lower_threshold,
                                             upper_threshold=upper_threshold,
                                             color=color,
                                             size=size)
