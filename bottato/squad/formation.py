from __future__ import annotations
import enum
import math
from typing import List

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
# from sc2.units import Units

from ..mixins import GeometryMixin, UnitReferenceMixin


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


class Formation:
    def __init__(
        self, bot: BotAI, formation_type: FormationType, unit_tags: List[int], offset: Point2
    ):
        self.bot = bot
        # generate specific formation positions
        self.formation_type = formation_type
        self.unit_tags = unit_tags
        self.offset = offset
        self.positions: List[Point2] = self.get_formation_positions()
        logger.debug(f"created formation {self.positions}")

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

    def get_formation_positions(self) -> List[Point2]:
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

    def get_line_positions(self) -> List[Point2]:
        return [
            Point2((
                i - len(self.unit_tags) / 2.0 + 0.5,
                -0.5
            ))
            for i in range(len(self.unit_tags))
        ]

    def get_column_positions(self) -> List[Point2]:
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

        positions = []
        row = column = 0
        for i in range(unit_count):
            positions.append(Point2((
                fill_pattern[column],
                row - 0.5
            )))
            column += 1
            if column == width:
                column = 0
                row += 1
        return positions

    def get_hollow_circle_positions(self) -> List[Point2]:
        positions: List[Point2] = list()
        # pack units shoulder to shoulder
        demographics = self.get_unit_demographics()
        circumference = demographics.maximum_unit_radius * len(self.unit_tags)
        radius = circumference / math.tau
        angular_separation = math.tau / len(self.unit_tags)
        for idx, unit_tag in enumerate(self.unit_tags):
            positions.append(
                Point2((
                    math.sin(idx * angular_separation) * radius,
                    math.cos(idx * angular_separation) * radius + radius,
                ))
            )
        return positions

    def get_hollow_half_circle_positions(self) -> List[Point2]:
        positions: List[Point2] = list()
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
                Point2((
                    math.sin(signum * half_idx * angular_separation)
                    * (
                        demographics.minimum_attack_range
                        + demographics.maximum_unit_radius * rank
                    ),
                    math.cos(signum * half_idx * angular_separation)
                    * (
                        demographics.minimum_attack_range
                        + demographics.maximum_unit_radius * rank
                    ),
                ))
            )
        return positions

    def get_solid_circle_positions(self) -> List[Point2]:
        positions: List[Point2] = list()
        # pack units shoulder to shoulder
        demographics = self.get_unit_demographics()
        circumference = demographics.maximum_unit_radius * len(self.unit_tags)
        radius = circumference / math.tau
        angular_separation = math.tau / len(self.unit_tags)
        for idx, unit_tag in enumerate(self.unit_tags):
            positions.append(
                Point2((
                    math.sin(idx * angular_separation) * radius,
                    math.cos(idx * angular_separation) * radius + radius,
                ))
            )
        return positions

    def get_unit_offset_from_leader(
        self, leader_offset: Point2
    ) -> list[Point2]:
        """positions for all formation members by tag"""
        unit_positions = []
        for position in self.positions:
            unit_position = position + self.offset - leader_offset
            unit_positions.append(unit_position * 2)
        return unit_positions


class ParentFormation(GeometryMixin, UnitReferenceMixin):
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
        logger.debug(f"Adding formation {formation_type.name} with unit tags {unit_tags}")
        self.formations.append(Formation(self.bot, formation_type, unit_tags, offset))

    def get_unit_destinations(
        self, formation_destination: Point2, leader: Unit, destination_facing: float = None
    ) -> dict[int, Point2]:
        # use first position in first formation as leader position
        leader_offset = self.formations[0].positions[0] + self.formations[0].offset
        leader_projected_position = self.predict_future_unit_position(leader, 0.5)

        distance_remaining = (leader.position - formation_destination).length
        logger.debug(f"formation distance remaining {distance_remaining}")
        formation_facing = destination_facing if distance_remaining < 5 and destination_facing else leader.facing
        logger.debug(f"formation facing {formation_facing}")

        unit_destinations = {}
        for formation in self.formations:
            # create list of positions to fill
            formation_offsets = formation.get_unit_offset_from_leader(leader_offset)
            rotated_offsets = self.apply_rotations(formation_facing, formation_offsets)
            positions = [leader_projected_position + offset for offset in rotated_offsets]

            # match positions to closest units
            unused_units = self.get_updated_unit_references_by_tags(formation.unit_tags)
            for position in positions:
                if not unused_units:
                    break
                unit = unused_units.closest_to(position)
                unused_units.remove(unit)
                if unit.tag == leader.tag:
                    unit_destinations[unit.tag] = formation_destination - leader_offset
                else:
                    unit_destinations[unit.tag] = position

        return unit_destinations
