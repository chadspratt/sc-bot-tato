from __future__ import annotations
import enum
import math

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
# from sc2.units import Units


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
        self, bot: BotAI, formation_type: FormationType, unit_tags: list[int], offset: Point2
    ):
        self.bot = bot
        # generate specific formation positions
        self.formation_type = formation_type
        self.unit_tags = unit_tags
        self.offset = offset
        # self.unit_count = unit_count
        # self.slowest_unit = None
        self.positions: list[FormationPosition] = self.get_formation_positions()
        logger.info(self.positions)

    def __repr__(self):
        buffer = ""
        for position in self.positions:
            buffer += f"{position}, "
        return buffer

    def get_unit_attack_range(self, unit: Unit) -> float:
        # PS: this might belong in the `Bottato` class, but it goes here for now
        #   The code itself is taken from `sc2.unit.target_in_range
        if unit.can_attack_ground:
            unit_attack_range = unit.ground_range
        elif unit.can_attack_air:
            unit_attack_range = unit.air_range
        else:
            unit_attack_range = False
        return unit_attack_range

    def get_unit_demographics(self) -> UnitDemographics:
        demographics = UnitDemographics()
        for unit_tag in self.unit_tags:
            unit: Unit = self.bot.units.by_tag(unit_tag)
            unit_attack_range = self.get_unit_attack_range(unit)
            demographics.maximum_unit_radius = max(unit.radius, demographics.maximum_unit_radius)
            if not unit_attack_range:
                continue
            demographics.minimum_attack_range = min(unit_attack_range, demographics.minimum_attack_range)
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

    def get_unit_offset_from_leader(
        self, leader_offset: Point2
    ) -> dict[int, Point2]:
        """positions for all formation members by tag"""
        unit_positions = {}
        for position in self.positions:
            unit_positions[position.unit_tag] = (
                position.offset + self.offset - leader_offset
            ) * 1.3
        return unit_positions


class ParentFormation:
    """Collection of formations which are offset from each other. tracks slowest unit as leader"""

    def __init__(self, bot: BotAI):
        self.bot = bot
        self.formations: list[Formation] = []

    def __repr__(self):
        buffer = ""
        for formation in self.formations:
            buffer += f"{formation}, "
        return buffer

    def clear(self):
        self.formations = []

    def add_formation(
        self,
        formation_type: FormationType,
        unit_tags: list[int],
        offset: Point2 = Point2((0, 0)),
    ):
        if not unit_tags:
            return
        logger.info(f"Adding formation {formation_type.name} with unit tags {unit_tags}")
        self.formations.append(Formation(self.bot, formation_type, unit_tags, offset))

    @property
    def game_position(self) -> Point2:
        for formation in self.formations:
            for position in formation.positions:
                try:
                    reference_unit = self.bot.units.by_tag(position.unit_tag)
                    unit_offset = position.offset + formation.offset
                    rotated_offset = self.apply_rotation(reference_unit.facing, point=unit_offset)
                    return reference_unit.position + rotated_offset
                except KeyError:
                    continue

    def get_unit_offset(self, unit: Unit) -> Point2:
        for formation in self.formations:
            logger.info(formation)
            for position in formation.positions:
                logger.info(position)
                if position.unit_tag == unit.tag:
                    return position.offset + formation.offset

    def apply_rotation(self, angle: float, point: Point2) -> Point2:
        # rotations default to facing along the y-axis, with a facing of pi/2
        rotation_needed = angle - math.pi / 2
        s_theta = math.sin(rotation_needed)
        c_theta = math.cos(rotation_needed)
        return self._apply_rotation(s_theta=s_theta, c_theta=c_theta, point=point)

    def _apply_rotation(self, *, s_theta: float, c_theta: float, point: Point2) -> Point2:
        new_x = point.x * c_theta - point.y * s_theta
        new_y = point.x * s_theta + point.y * c_theta
        return Point2((new_x, new_y))

    def apply_rotations(self, angle: float, points: dict[int, Point2] = None):
        s_theta = math.sin(angle)
        c_theta = math.cos(angle)
        new_positions = {}
        for unit_tag, point in points.items():
            new_positions[unit_tag] = self._apply_rotation(s_theta=s_theta, c_theta=c_theta, point=point)
        return new_positions

    def get_unit_destinations(
        self, formation_destination: Point2, leader: Unit, facing: float = None
    ) -> dict[int, Point2]:
        unit_offsets = {}
        leader_offset = self.get_unit_offset(leader)
        # leader destination
        for formation in self.formations:
            unit_offsets.update(
                formation.get_unit_offset_from_leader(leader_offset)
            )

        if facing is None:
            facing = leader.facing
        unit_offsets = self.apply_rotations(facing, unit_offsets)
        unit_destinations = dict([(unit_tag, offset + leader.position) for unit_tag, offset in unit_offsets.items()])
        unit_destinations[leader.tag] = formation_destination - unit_offsets[leader.tag]
        # TODO: apply rotation matrix
        return unit_destinations
