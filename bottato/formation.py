from __future__ import annotations
import enum
import math

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units


class FormationType(enum.Enum):
    SOLID_CIRCLE = 0
    HOLLOW_CIRCLE = 1
    LINE = 3
    SQUARE = 4


line = [[[0]]] * 9

# fan_out = [
#     [[1], [ ], [ ], [ ], [1]],
#     [[ ], [ ], [1], [ ], [ ]],
# ]

# marine_diamond = [
#     [[ ], [ ], [ ], [ ], [ ], [1], [ ], [ ], [ ], [ ], [ ]],
#     [[ ], [ ], [ ], [ ], [1], [ ], [1], [ ], [ ], [ ], [ ]],
#     [[ ], [ ], [ ], [1], [ ], [ ], [ ], [1], [ ], [ ], [ ]],
#     [[ ], [ ], [1], [ ], [ ], [ ], [ ], [ ], [1], [ ], [ ]],
#     [[ ], [1], [ ], [ ], [ ], [ ], [ ], [ ], [ ], [1], [ ]],
#     [[1], [ ], [ ], [ ], [ ], [ ], [ ], [ ], [ ], [ ], [1]],
#     [[ ], [1], [ ], [ ], [ ], [ ], [ ], [ ], [ ], [1], [ ]],
#     [[ ], [ ], [1], [ ], [ ], [ ], [ ], [ ], [1], [ ], [ ]],
#     [[ ], [ ], [ ], [1], [ ], [ ], [ ], [1], [ ], [ ], [ ]],
#     [[ ], [ ], [ ], [ ], [1], [ ], [1], [ ], [ ], [ ], [ ]],
#     [[ ], [ ], [ ], [ ], [ ], [1], [ ], [ ], [ ], [ ], [ ]],
# ]
# marine_diamond = [
#     [[marine_diamond], [ ], [ ], [ ], [ ], [marine_diamond]],
# ]
# diamonds = [
#     [[], [      ], [marine_line, raven_line], [      ], [diamond]],
#     [[      ], [      ], [diamond], [      ], [      ]],
# ]
column = [
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
    [[1], [1]],
]


class FormationPosition:
    def __init__(self, x_offset, y_offset, unit_tag):
        # front-center is 0, 0
        # y is greater than 0 always (they travel in the y direction)
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.unit_tag: int = unit_tag

    @property
    def offset(self):
        return Point2(self.x_offset, self.y_offset)


class Formation:
    def __init__(self, formation_type: FormationType, units: Units, offset: Point2):
        # generate specific formation positions
        self.formation_type = formation_type
        self.unit_tags = units.tags
        self.offset = offset
        # self.unit_count = unit_count
        # self.slowest_unit = None
        self.positions: list[FormationPosition] = self.get_formation_positions()

    def get_formation_positions(self):
        positions = []
        if self.formation_type == FormationType.LINE:
            positions = [
                FormationPosition(
                    x_offset=i - len(self.units), y_offset=0, unit_tag=unit_tag
                ) for i, unit_tag in enumerate(self.unit_tags)
            ]
        return positions

    def get_unit_position_from_leader(self, leader_offset: Point2, leader_position: Point2) -> dict[int, Point2]:
        """positions for all formation members by tag"""
        unit_positions = {}
        for position in self.positions:
            unit_positions[position.unit_tag] = position.offset + self.offset - leader_offset + leader_position
        return unit_positions


class ParentFormation:
    """Collection of formations which are offset from each other. tracks slowest unit as leader"""
    def __init__(self):
        self.game_position: Point2 = None  # of the front-center of the formations
        self.formations: list[Formation] = []

    def clear(self):
        self.formations = []

    def add_formation(self, formation_type: FormationType, units: Units, offset: Point2 = Point2(0, 0)):
        self.formations.append(Formation(formation_type, units, offset))

    def get_leader_offset(self, leader: Unit) -> Point2:
        for formation in self.formations:
            for postion in formation.positions:
                if postion.unit_tag == leader.tag:
                    return postion.offset + formation.offset

    def apply_rotation(self, positions: dict[int, Point2], angle: float):
        s_theta = math.sin(angle)
        c_theta = math.cos(angle)
        for position in positions.values():
            new_x = position.x * c_theta + position.y * s_theta
            new_y = position.x * s_theta - position.x * s_theta
            position.x = new_x
            position.y = new_y

    def get_unit_destinations(self, formation_destination: Point2, leader: Unit) -> dict[int, Point2]:
        unit_destinations = {}
        leader_offset = self.get_leader_offset(leader)
        # leader destination
        for formation in self.formations:
            unit_destinations.update(formation.get_unit_position_from_leader(leader_offset, leader.position))
        leader_destination = formation_destination - leader_offset
        unit_destinations[leader.tag] = leader_destination
        # TODO: apply rotation matrix
        self.apply_rotation(unit_destinations, leader.facing)
        return unit_destinations
