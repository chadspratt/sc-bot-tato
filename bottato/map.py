from loguru import logger

from sc2.bot_ai import BotAI
from sc2.pixel_map import PixelMap
from sc2.position import Point2


class Map:
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.distance_from_edge: list[list[int]] = []
        self.open_area_midpoints: list[Point2] = []
        self.choke_midpoints: dict[Point2, list[(Point2, Point2)]] = {}
        self.init_distance_from_edge()
        self.init_open_area_midpoints()
        self.init_open_area_connections()

    def init_distance_from_edge(self):
        pathing_grid: PixelMap = self.bot.game_info.pathing_grid
        # init array with unpathable and put 9999 placeholder for other spots
        self.distance_from_edge.clear()
        for x in range(pathing_grid.width):
            self.distance_from_edge.append([])
            for y in range(pathing_grid.height):
                # keep 0 as 0, change 1 to 9999 to represent uncalculated
                self.distance_from_edge[x][y] = pathing_grid[(x, y)] * 9999

        new_spot_found = True
        while new_spot_found:
            new_spot_found = False
            for x in range(pathing_grid.width):
                for y in range(pathing_grid.height):
                    if self.distance_from_edge[x][y] >= 9999:
                        new_spot_found = True
                        self.distance_from_edge[x][y] = self.lowest_neighbor(x, y) + 1

    def lowest_neighbor(self, x, y) -> int:
        return min([self.distance_from_edge[p.x][p.y] for p in Point2(x, y).neighbors8])

    def has_higher_neighbor(self, point: Point2) -> bool:
        value = self.distance_from_edge[point.x][point.y]
        for neighbor in point.neighbors8:
            if self.distance_from_edge[neighbor.x][neighbor.y] > value:
                return True
        return False

    def init_open_area_midpoints(self):
        self.open_area_midpoints.clear()
        for x in range(len(self.distance_from_edge)):
            for y in range(len(self.distance_from_edge[x])):
                point: Point2 = Point2(x, y)
                if not self.has_higher_neighbor(point):
                    # will insert multiple points if there are adjacent ties, should merge these
                    self.open_area_midpoints.append(point)
                    logger.info(f"midpoint ({x}, {y}) is {self.distance_from_edge[x][y]} from edge")

    def init_open_area_connections(self):
        midpoint: Point2
        for midpoint in self.open_area_midpoints:
            self.choke_midpoints[midpoint] = self.find_choke_midpoints(midpoint)

    def find_choke_midpoints(self, midpoint: Point2):
        choke_points: list[Point2] = []
        next_points: list[Point2] = [midpoint]
        visited: set[Point2] = set()
        while next_points:
            new_next_points: list[Point2] = []
            for next_point in next_points:
                current_distance_from_edge: int = self.distance_from_edge[next_point]
                adjacent_points = next_point.neighbors8
                for point in adjacent_points:
                    if (point.x, point.y) in visited:
                        continue
                    visited.add((point.x, point.y))
                    distance = self.distance_from_edge[point.x][point.y]
                    if distance > current_distance_from_edge:
                        # exit of choke found
                        choke_points.append((point, next_point))
                    elif distance > 0:
                        new_next_points.append(point)
            next_points = new_next_points

    # open areas are adjacent if there is one choke point between them
