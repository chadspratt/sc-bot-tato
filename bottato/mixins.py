import math
import random
from loguru import logger
from typing import List
from time import perf_counter

from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3


class UnitReferenceMixin:
    class UnitNotFound(Exception):
        pass

    def get_updated_unit_reference(self, unit: Unit) -> Unit:
        if unit is None:
            raise self.UnitNotFound(
                "unit is None"
            )
        return self.get_updated_unit_reference_by_tag(unit.tag)

    def get_updated_unit_reference_by_tag(self, tag: int) -> Unit:
        try:
            return self.bot.all_units.by_tag(tag)
        except KeyError:
            raise self.UnitNotFound(
                f"Cannot find unit with tag {tag}; maybe they died"
            )

    def get_updated_unit_references(self, units: Units) -> Units:
        _units = Units([], bot_object=self.bot)
        for unit in units:
            try:
                _units.append(self.get_updated_unit_reference(unit))
            except self.UnitNotFound:
                logger.info(f"Couldn't find unit {unit}!")
        return _units

    def get_updated_unit_references_by_tags(self, tags: List[int]) -> Units:
        _units = Units([], bot_object=self.bot)
        for tag in tags:
            try:
                _units.append(self.get_updated_unit_reference_by_tag(tag))
            except self.UnitNotFound:
                logger.debug(f"Couldn't find unit {tag}!")
        return _units


class GeometryMixin:
    def convert_point2_to_3(self, point2: Point2) -> Point3:
        height: float = self.bot.get_terrain_z_height(point2)
        return Point3((point2.x, point2.y, height))

    def get_facing(self, start_position: Point2, end_position: Point2):
        angle = math.atan2(
            end_position.y - start_position.y, end_position.x - start_position.x
        )
        if angle < 0:
            angle += math.pi * 2
        return angle

    def apply_rotation(self, angle: float, point: Point2, reverse_direction=False) -> Point2:
        # rotations default to facing along the y-axis, with a facing of pi/2
        logger.debug(f"apply_rotation at angle {angle}")
        rotation_needed = math.pi / 2 - angle if reverse_direction else angle - math.pi / 2

        logger.debug(f">> adjusted to {rotation_needed}")
        s_theta = math.sin(rotation_needed)
        c_theta = math.cos(rotation_needed)
        rotated = self._apply_rotation(s_theta=s_theta, c_theta=c_theta, point=point)
        logger.debug(f"rotation calculated from {point} to {rotated}")
        return rotated

    def _apply_rotation(self, *, s_theta: float, c_theta: float, point: Point2) -> Point2:
        new_x = point.x * c_theta - point.y * s_theta
        new_y = point.x * s_theta + point.y * c_theta
        return Point2((new_x, new_y))

    def apply_rotations(self, angle: float, points: list[Point2] = None):
        # rotations default to facing along the y-axis, with a facing of pi/2
        rotation_needed = angle - math.pi / 2
        s_theta = math.sin(rotation_needed)
        c_theta = math.cos(rotation_needed)
        return [
            self._apply_rotation(s_theta=s_theta, c_theta=c_theta, point=point) for point in points
        ]

    def predict_future_unit_position(self,
                                     unit: Unit,
                                     seconds_ahead: float,
                                     check_pathable: bool = True,
                                     ) -> Point2:
        unit_speed = unit.calculate_speed()

        remaining_distance = unit_speed * seconds_ahead

        forward_unit_vector = self.apply_rotation(unit.facing, Point2([0, 1]))

        if not check_pathable:
            return unit.position + forward_unit_vector * remaining_distance

        future_position = unit.position
        while True:
            if remaining_distance < 1:
                forward_unit_vector *= remaining_distance
            potential_position = future_position + forward_unit_vector
            if not self.bot.in_pathing_grid(potential_position):
                return future_position

            future_position = potential_position

            remaining_distance -= 1
            if remaining_distance <= 0:
                return future_position


class TimerMixin:
    def start_timer(self, timer_name: str) -> None:
        if not hasattr(self, "timers"):
            self.timers = {}
        if timer_name not in self.timers:
            self.timers[timer_name] = {"start": perf_counter(), "total": 0}
        else:
            self.timers[timer_name]["start"] = perf_counter()

    def stop_timer(self, timer_name: str) -> None:
        timer = self.timers[timer_name]
        timer["total"] += perf_counter() - timer["start"]

    def print_timers(self, prefix: str = '') -> None:
        for timer_name in self.timers.keys():
            timer = self.timers[timer_name]
            logger.info(f"{prefix}{timer_name} execution time: {timer["total"]}")


class DebugMixin:
    def random_color(self) -> tuple[int, int, int]:
        rgb = [0, 0, 0]
        highlow_index = random.randint(0, 2)
        high_or_low = random.randint(0, 1) > 0
        for i in range(3):
            if i == highlow_index:
                rgb[i] = 255 if high_or_low else 0
            else:
                rgb[i] = random.randint(0, 255)
        return tuple(rgb)
