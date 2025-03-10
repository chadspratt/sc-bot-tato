
from sc2.bot_ai import BotAI

from utils import change_destructible_status_in_grid
import numpy as np


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
