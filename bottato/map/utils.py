import numpy as np

from sc2.bot_ai import BotAI
from sc2.game_info import Ramp
from sc2.position import Point2
from sc2.unit import Unit

# from MapAnalyzer.constructs import MDRamp, VisionBlockerArea
# from .cext import CMapChoke
# from .settings import ROOT_DIR
from bottato.map.destructibles import destructibles


def change_destructible_status_in_grid(grid: np.ndarray, unit: Unit, status: int):
    """
    Set destructable positions to status, modifies the grid in place
    """
    type_id = unit.type_id
    pos = unit.position
    name = unit.name

    # this is checked with name because the id of the small mineral destructables
    # has changed over patches and may cause problems
    if name == "MineralField450":
        x = int(pos[0]) - 1
        y = int(pos[1])
        grid[x:(x + 2), y] = status
    elif type_id in destructibles["2x2"]:
        w = 2
        h = 2
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), y:(y + h)] = status
    elif type_id in destructibles["2x4"]:
        w = 2
        h = 4
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), y:(y + h)] = status
    elif type_id in destructibles["2x6"]:
        w = 2
        h = 6
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), y:(y + h)] = status
    elif type_id in destructibles["4x2"]:
        w = 4
        h = 2
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), y:(y + h)] = status
    elif type_id in destructibles["4x4"]:
        w = 4
        h = 4
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), y:(y + h)] = status
    elif type_id in destructibles["6x2"]:
        w = 6
        h = 2
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), y:(y + h)] = status
    elif type_id in destructibles["6x6"]:
        # for some reason on some maps like death aura
        # these rocks have a bit weird sizes
        # on golden wall this is an exact match
        # on death aura the height is one coordinate off
        # and it varies whether the position is centered too high or too low
        w = 6
        h = 6
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), (y + 1):(y + h - 1)] = status
        grid[(x + 1):(x + w - 1), y:(y + h)] = status
    elif type_id in destructibles["12x4"]:
        w = 12
        h = 4
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), y:(y + h)] = status
    elif type_id in destructibles["4x12"]:
        w = 4
        h = 12
        x = int(pos[0] - w / 2)
        y = int(pos[1] - h / 2)
        grid[x:(x + w), y:(y + h)] = status
    elif type_id in destructibles["BLUR"]:
        x_ref = int(pos[0] - 5)
        y_pos = int(pos[1])
        grid[(x_ref + 6):(x_ref + 6 + 2), y_pos + 4] = status
        grid[(x_ref + 5):(x_ref + 5 + 4), y_pos + 3] = status
        grid[(x_ref + 4):(x_ref + 4 + 6), y_pos + 2] = status
        grid[(x_ref + 3):(x_ref + 3 + 7), y_pos + 1] = status
        grid[(x_ref + 2):(x_ref + 2 + 7), y_pos] = status
        grid[(x_ref + 1):(x_ref + 1 + 7), y_pos - 1] = status
        grid[(x_ref + 0):(x_ref + 0 + 7), y_pos - 2] = status
        grid[(x_ref + 0):(x_ref + 0 + 6), y_pos - 3] = status
        grid[(x_ref + 1):(x_ref + 1 + 4), y_pos - 4] = status
        grid[(x_ref + 2):(x_ref + 2 + 2), y_pos - 5] = status

    elif type_id in destructibles["ULBR"]:
        x_ref = int(pos[0] - 5)
        y_pos = int(pos[1])
        grid[(x_ref + 6):(x_ref + 6 + 2), y_pos - 5] = status
        grid[(x_ref + 5):(x_ref + 5 + 4), y_pos - 4] = status
        grid[(x_ref + 4):(x_ref + 4 + 6), y_pos - 3] = status
        grid[(x_ref + 3):(x_ref + 3 + 7), y_pos - 2] = status
        grid[(x_ref + 2):(x_ref + 2 + 7), y_pos - 1] = status
        grid[(x_ref + 1):(x_ref + 1 + 7), y_pos] = status
        grid[(x_ref + 0):(x_ref + 0 + 7), y_pos + 1] = status
        grid[(x_ref + 0):(x_ref + 0 + 6), y_pos + 2] = status
        grid[(x_ref + 1):(x_ref + 1 + 4), y_pos + 3] = status
        grid[(x_ref + 2):(x_ref + 2 + 2), y_pos + 4] = status


def fix_map_ramps(bot: BotAI):
    """
    following https://github.com/BurnySc2/python-sc2/blob/ffb9bd43dcbeb923d848558945a8c59c9662f435/sc2/game_info.py#L246
    to fix burnysc2 ramp objects by removing destructables
    """
    pathing_grid = bot.game_info.pathing_grid.data_numpy.T.copy()
    for dest in bot.destructables:
        change_destructible_status_in_grid(pathing_grid, dest, 1)

    pathing = np.ndenumerate(pathing_grid.T)

    def equal_height_around(tile):
        sliced = bot.game_info.terrain_height.data_numpy[tile[1] - 1: tile[1] + 2, tile[0] - 1: tile[0] + 2]
        return len(np.unique(sliced)) == 1

    map_area = bot.game_info.playable_area
    points = [
        Point2((a, b))
        for (b, a), value in pathing
        if (value == 1
            and map_area.x <= a < map_area.x + map_area.width
            and map_area.y <= b < map_area.y + map_area.height
            and bot.game_info.placement_grid[(a, b)] == 0)
    ]
    ramp_points: frozenset[Point2] = frozenset(point for point in points if not equal_height_around(point))
    vision_blockers = set(point for point in points if equal_height_around(point))
    ramps = [Ramp(group, bot.game_info) for group in bot.game_info._find_groups(ramp_points)]
    return ramps, vision_blockers
