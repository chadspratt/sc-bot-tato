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
    HOLLOW_HALF_CIRCLE = 5


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


class UnitDemographics:
    def __init__(self):
        self.minimum_attack_range: float = math.inf
        self.maximum_unit_radius: float = 0


class FormationPosition:
    def __init__(self, x_offset, y_offset, unit_tag):
        # front-center is 0, 0
        # y is greater than 0 always (they travel in the y direction)
        self.x_offset = x_offset
        self.y_offset = y_offset
        self.unit_tag: int = unit_tag

    def __str__(self):
        return f"{self.unit_tag}: ({self.x_offset}, {self.y_offset})"

    @property
    def offset(self):
        return Point2((self.x_offset, self.y_offset))


class Formation:
    def __init__(
        self, formation_type: FormationType, unit_tags: list[int], offset: Point2
    ):
        # generate specific formation positions
        self.formation_type = formation_type
        self.unit_tags = unit_tags
        self.offset = offset
        # self.unit_count = unit_count
        # self.slowest_unit = None
        self.positions: list[FormationPosition] = self.get_formation_positions()

    def get_unit_attack_range(self, unit: Unit) -> float:
        # PS: this might belong in the `Bottato` class, but it goes here for now
        #   The code itself is taken from `sc2.unit.target_in_range
        if self.can_attack_ground and not target.is_flying:
            unit_attack_range = self.ground_range
        elif self.can_attack_air and (
            target.is_flying or target.type_id == UNIT_COLOSSUS
        ):
            unit_attack_range = self.air_range
        else:
            unit_attack_range = False
        return unit_attack_range

    def get_unit_demographics(self) -> UnitDemographics:
        demographics = UnitDemographics()
        for unit_tag in self.unit_tags:
            unit = self.bot.units.by_tag(unit_tag)
            unit_attack_range = self.get_unit_attack_range(unit)
            maximum_unit_radius = max(unit_radius, maximum_unit_radius)
            if not unit_attack_range:
                continue
            minimum_attack_range = min(radius, unit_attack_range)
        return demographics

    def get_formation_positions(self):
        positions = []
        if self.formation_type == FormationType.LINE:
            positions = [
                FormationPosition(
                    x_offset=i - len(self.unit_tags), y_offset=0, unit_tag=unit_tag
                )
                for i, unit_tag in enumerate(self.unit_tags)
            ]
        elif self.formation_type == FormationType.HOLLOW_CIRCLE:
            # pack units shoulder to shoulder
            demographics = self.get_unit_demographics()
            circumference = demographics.maximum_unit_radius * len(self.unit_tags)
            radius = circumference / math.tau
            angular_separation = math.tau / len(self.unit_tags)
            positions = []
            for idx, unit_tag in enumerate(self.unit_tags):
                positions.append(
                    FormationPosition(
                        x_offset=math.sin(idx * angular_separation) * radius,
                        y_offset=math.cos(idx * angular_separation) * radius + radius,
                        unit_tag=unit_tag,
                    )
                )
        elif self.formation_type == FormationType.HOLLOW_HALF_CIRCLE:
            # use minimum unit attack radius as radius of circle (should
            #   fill from bottom up)
            # place units shoulder to shoulder, and form extra half circles
            #   (radial pattern) behind first rank with extra units
            demographics = self.get_unit_demographics()
            swept_arc_length = math.pi * demographics.minimum_attack_range
            max_units_in_radius = swept_arc_length // demographics.maximum_unit_radius
            angular_separation = math.pi / max_units_in_radius
            rank = 0
            positions = []
            for idx, unit_tag in enumerate(self.unit_tags, start=1):
                if idx > (rank + 1) * max_units_in_radius:
                    rank += 1
                _idx = idx - (rank * max_units_in_radius)
                signum = -1
                if _idx % 2 == 1:
                    signum = 1
                half_idx = _idx // 2
                positions.append(
                    FormationPosition(
                        x_offset=math.sin(signum * half_idx * angular_separation)
                        * (
                            demographics.minimum_attack_range
                            + demographics.maximum_unit_radius * rank
                        ),
                        y_offset=math.cos(signum * half_idx * angular_separation)
                        * (
                            demographics.minimum_attack_range
                            + demographics.maximum_unit_radius * rank
                        ),
                        unit_tag=unit_tag,
                    )
                )
        return positions

    def get_unit_position_from_leader(
        self, leader_offset: Point2, leader_position: Point2
    ) -> dict[int, Point2]:
        """positions for all formation members by tag"""
        unit_positions = {}
        for position in self.positions:
            unit_positions[position.unit_tag] = (
                position.offset + self.offset - leader_offset + leader_position
            )
        return unit_positions


class ParentFormation:
    """Collection of formations which are offset from each other. tracks slowest unit as leader"""

    def __init__(self):
        self.game_position: Point2 = None  # of the front-center of the formations
        self.formations: list[Formation] = []

    def clear(self):
        self.formations = []

    def add_formation(
        self,
        formation_type: FormationType,
        units: Units,
        offset: Point2 = Point2((0, 0)),
    ):
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
            new_y = -position.x * s_theta + position.y * c_theta
            position.x = new_x
            position.y = new_y

    def get_unit_destinations(
        self, formation_destination: Point2, leader: Unit
    ) -> dict[int, Point2]:
        unit_destinations = {}
        leader_offset = self.get_leader_offset(leader)
        # leader destination
        for formation in self.formations:
            unit_destinations.update(
                formation.get_unit_position_from_leader(leader_offset, leader.position)
            )
        leader_destination = formation_destination - leader_offset
        unit_destinations[leader.tag] = leader_destination
        # TODO: apply rotation matrix
        self.apply_rotation(unit_destinations, leader.facing)
        return unit_destinations
