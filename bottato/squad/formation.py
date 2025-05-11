from __future__ import annotations
import enum
import math
from typing import List

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
# from sc2.units import Units

from ..mixins import GeometryMixin, UnitReferenceMixin
from ..map.map import Map


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

    def get_unit_offsets_from_reference_point(
        self, reference_point: Point2
    ) -> list[Point2]:
        """positions for all formation members by tag"""
        unit_positions = []
        for position in self.positions:
            unit_position = position + self.offset - reference_point
            unit_positions.append(unit_position * 2)
        return unit_positions


class ParentFormation(GeometryMixin, UnitReferenceMixin):
    """Collection of formations which are offset from each other. Translates between formation coords and game coords"""

    def __init__(self, bot: BotAI, map: Map):
        self.bot = bot
        self.map = map
        self.formations: List[Formation] = []
        self.front_center: Point2 = None
        self.path: List[Point2] = []
        self.destination: Point2 = None

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
        self, formation_destination: Point2, units: Units, destination_facing: float = None
    ) -> dict[int, Point2]:
        unit_destinations = {}
        reference_point: Point2 = Point2((0, 0))
        facing = destination_facing

        if not self.front_center:
            # initialize
            self.front_center = units.closest_n_units(formation_destination, 1).first.position
        distance_remaining = (self.front_center - formation_destination).length
        if distance_remaining < 5:
            self.destination = formation_destination
            logger.debug(f"distance to {self.destination} < 5")
        else:
            self.path = self.map.get_path_points(self.front_center, formation_destination)
            # destination should be next waypoint, but need to
            next_waypoint = self.path[1] if len(self.path) > 1 else formation_destination
            self.front_center = self.calculate_formation_front_center(units, next_waypoint)
            # limit front_center jumping around
            # self.front_center = self.front_center.towards(new_front_center, 2, limit=True)

            if self.path and len(self.path) > 1:
                logger.debug(f"following path {self.path} to {self.destination}")
                self.destination = self.front_center.towards(self.path[1], distance=2, limit=True)
            else:
                logger.debug(f"heading directly to {self.destination}")
                # if no path, tell all units to go to the destination. happens if already in destination zone or if reference point passes over non-pathable area
                self.destination = formation_destination

            if distance_remaining > 5:
                facing = self.get_facing(self.front_center, self.destination)
                for formation in self.formations:
                    if self.closest_unit.tag in formation.unit_tags:
                        reference_point = formation.offset
                        break

        for formation in self.formations:
            # create list of positions to fill
            formation_offsets = formation.get_unit_offsets_from_reference_point(reference_point)
            rotated_offsets = self.apply_rotations(facing, formation_offsets)
            positions = [self.destination + offset for offset in rotated_offsets]

            # match positions to closest units
            formation_units = self.get_updated_unit_references_by_tags(formation.unit_tags)
            for position in positions:
                if not formation_units:
                    break
                unit = formation_units.closest_to(position)
                valid_position = position if unit.is_flying else self.map.get_pathable_position(position, unit)
                formation_units.remove(unit)
                unit_destinations[unit.tag] = valid_position

        return unit_destinations

    def calculate_formation_front_center(self, units: Units, destination: Point2) -> Point2:
        close_units = units.closer_than(10, self.front_center)
        in_formation_units: Units = close_units if close_units else units
        units_center = in_formation_units.center

        path_units = units.filter(lambda u: not u.is_flying)
        if path_units.empty:
            path_units = units
        self.path = self.map.get_shortest_path(path_units, destination)
        closest_position = self.path[0]
        self.closest_unit = units.closest_to(closest_position)

        # # find waypoint beyond the units
        next_waypoint = destination
        next_waypoint_index = 1
        distance = 0
        while distance < 2 and next_waypoint_index < len(self.path):
            next_waypoint = self.path[next_waypoint_index]
            distance = closest_position.distance_to(next_waypoint)
            next_waypoint_index += 1
        closest_elevation = self.bot.get_terrain_z_height(closest_position)
        intersect_point: Point2
        if units_center.x == next_waypoint.x:
            # avoid div by zero, but is also much simpler
            intersect_point = Point2((units_center.x, closest_position.y))
        elif units_center.y == next_waypoint.y:
            intersect_point = Point2((units_center.y, closest_position.x))
        else:
            # make triangle of destination, frontline center, and nearest unit to destination
            # treating frontline to destination as base, find point where triangle height intersects base
            # use this point as (0, 0) position of formation
            dest_center_slope: float = (units_center.y - next_waypoint.y) / (units_center.x - next_waypoint.x)
            dest_center_b = units_center.y - dest_center_slope * units_center.x
            closest_front_slope: float = -1 / dest_center_slope
            closest_front_b: float = closest_position.y - closest_front_slope * closest_position.x
            x_intersect = (closest_front_b - dest_center_b) / (dest_center_slope - closest_front_slope)
            y_intersect = x_intersect * dest_center_slope + dest_center_b
            intersect_point = Point2((x_intersect, y_intersect))
        new_front_center = intersect_point.towards(next_waypoint, 1, limit=True)
        while abs(self.bot.get_terrain_z_height(new_front_center) - closest_elevation) > 0.8:
            new_front_center = new_front_center.towards(closest_position, 1, limit=True)
        return new_front_center
