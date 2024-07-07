from __future__ import annotations
import enum
import math
from typing import List

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
# from sc2.units import Units

from ..mixins import GeometryMixin


class FormationType(enum.Enum):
    SOLID_CIRCLE = 0
    HOLLOW_CIRCLE = 1
    LINE = 3
    SQUARE = 4
    HOLLOW_HALF_CIRCLE = 5
    COLUMNS = 6


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

    def __repr__(self):
        return f"{self.unit_tag}: ({self.x_offset}, {self.y_offset})"

    def __str__(self):
        return self.__repr__()

    @property
    def offset(self):
        return Point2((self.x_offset, self.y_offset))


class Formation:
    def __init__(
        self, bot: BotAI, formation_type: FormationType, unit_tags: List[int], offset: Point2
    ):
        self.bot = bot
        # generate specific formation positions
        self.formation_type = formation_type
        self.unit_tags = unit_tags
        self.offset = offset
        # self.unit_count = unit_count
        # self.slowest_unit = None
        self.positions: List[FormationPosition] = self.get_formation_positions()
        logger.info(f"created formation {self.positions}")

    def __repr__(self):
        return f"[{self.formation_type}]: " + ", ".join([str(position) for position in self.positions])

    def __str__(self):
        return self.__repr__()

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

    def get_formation_positions(self) -> List[FormationPosition]:
        positions = []
        if self.formation_type == FormationType.LINE:
            positions = self.get_line_positions()
        elif self.formation_type == FormationType.COLUMNS:
            positions = self.get_column_positions()
        elif self.formation_type == FormationType.HOLLOW_CIRCLE:
            positions = self.get_hollow_circle_positions()
        elif self.formation_type == FormationType.HOLLOW_HALF_CIRCLE:
            positions = self.get_hollow_half_circle_positions()
        elif self.formation_type == FormationType.SOLID_CIRCLE:
            positions = self.get_solid_circle_positions()
        return positions

    def get_line_positions(self) -> List[FormationPosition]:
        return [
            FormationPosition(
                x_offset=i - len(self.unit_tags) / 2.0 + 0.5, y_offset=-0.5, unit_tag=unit_tag
            )
            for i, unit_tag in enumerate(self.unit_tags)
        ]

    def get_column_positions(self) -> List[FormationPosition]:
        unit_count = len(self.unit_tags)
        width = unit_count
        length = 1
        while width > length * 3 and width > 1:
            width -= 1
            length = unit_count / width
        fill_pattern = []
        for i in range(width):
            adjustment = i // 2 if i % 2 == 0 else -i // 2
            fill_pattern.append(adjustment)
        # logger.info(f"fucking hell, unit_count {unit_count}, width {width}, length {length}")

        positions = []
        row = column = 0
        for unit_tag in self.unit_tags:
            positions.append(FormationPosition(
                x_offset=fill_pattern[column], y_offset=row - 0.5, unit_tag=unit_tag
            ))
            column += 1
            if column == width:
                column = 0
                row += 1
        return positions

    def get_hollow_circle_positions(self) -> List[FormationPosition]:
        positions: List[FormationPosition] = list()
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
        return positions

    def get_hollow_half_circle_positions(self) -> List[FormationPosition]:
        positions: List[FormationPosition] = list()
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

    def get_solid_circle_positions(self) -> List[FormationPosition]:
        positions: List[FormationPosition] = list()
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


class ParentFormation(GeometryMixin):
    """Collection of formations which are offset from each other. Translates between formation coords and game coords"""

    def __init__(self, bot: BotAI):
        self.bot = bot
        self.formations: List[Formation] = []

    def __repr__(self):
        return ", ".join([str(formation) for formation in self.formations])

    def clear(self):
        self.formations = []

    def add_formation(
        self,
        formation_type: FormationType,
        unit_tags: List[int],
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
            for position in formation.positions:
                if position.unit_tag == unit.tag:
                    return position.offset + formation.offset

    def get_unit_destinations(
        self, formation_destination: Point2, leader: Unit, destination_facing: float = None
    ) -> dict[int, Point2]:
        unit_offsets = {}
        leader_offset = self.get_unit_offset(leader)
        # leader destination
        for formation in self.formations:
            unit_offsets.update(
                formation.get_unit_offset_from_leader(leader_offset)
            )

        distance_remaining = (self.game_position - formation_destination).length
        logger.debug(f"formation distance remaining {distance_remaining}")
        formation_facing = destination_facing if distance_remaining < 5 and destination_facing else leader.facing
        logger.debug(f"formation facing {formation_facing}")

        logger.debug(f"unit offsets {unit_offsets}")
        rotated_offsets = self.apply_rotations(formation_facing, unit_offsets)
        logger.debug(f"rotated offsets {rotated_offsets}")
        if destination_facing:
            rotated_offsets[leader.tag] = self.apply_rotation(destination_facing, unit_offsets[leader.tag])
        unit_destinations = dict([(unit_tag, offset + leader.position) for unit_tag, offset in rotated_offsets.items()])
        unit_destinations[leader.tag] = formation_destination - leader_offset

        return unit_destinations
