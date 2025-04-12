import math
import random
from loguru import logger
from typing import List
from time import perf_counter

from sc2.game_data import Cost
from sc2.ids.unit_typeid import UnitTypeId
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
                logger.debug(f"Couldn't find unit {unit}!")
        return _units

    def get_updated_unit_references_by_tags(self, tags: List[int]) -> Units:
        _units = Units([], bot_object=self.bot)
        for tag in tags:
            try:
                _units.append(self.get_updated_unit_reference_by_tag(tag))
            except self.UnitNotFound:
                logger.debug(f"Couldn't find unit {tag}!")
        return _units

    def count_units_by_property(self, units: Units) -> dict[UnitTypeId, int]:
        counts: dict[UnitTypeId, int] = {
            'flying': 0,
            'ground': 0,
            'armored': 0,
            'biological': 0,
            'hidden': 0,
            'light': 0,
            'mechanical': 0,
            'psionic': 0,
            'attacks ground': 0,
            'attacks air': 0,
        }

        unit: Unit
        for unit in units:
            if unit.is_hallucination:
                continue
            if unit.is_flying:
                counts['flying'] += 1
            else:
                counts['ground'] += 1
            if unit.is_armored:
                counts['armored'] += 1
            if unit.is_biological:
                counts['biological'] += 1
            if unit.is_burrowed or unit.is_cloaked or not unit.is_visible:
                counts['hidden'] += 1
            if unit.is_light:
                counts['light'] += 1
            if unit.is_mechanical:
                counts['mechanical'] += 1
            if unit.is_psionic:
                counts['psionic'] += 1
            if unit.can_attack_ground:
                counts['attacks ground'] += 1
            if unit.can_attack_air:
                counts['attacks air'] += 1

        return counts

    def get_army_value(self, units: Units) -> float:
        army_value = 0
        type_costs = {}
        for unit in units:
            if unit.is_structure:
                continue
            if unit.type_id not in type_costs:
                try:
                    cost: Cost = self.bot.calculate_cost(unit.type_id)
                except AttributeError:
                    continue
                supply = self.bot.calculate_supply_cost(unit.type_id)
                type_costs[unit.type_id] = ((cost.minerals * 0.9) + cost.vespene) * supply
            army_value += type_costs[unit.type_id]
        return army_value


class GeometryMixin:
    def convert_point2_to_3(self, point2: Point2) -> Point3:
        height: float = self.bot.get_terrain_z_height(point2) + 1
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
                                     frame_vector: Point2 = None
                                     ) -> Point2:
        unit_speed: float
        forward_unit_vector: Point2
        max_speed = unit.calculate_speed()
        if frame_vector:
            speed_per_frame = frame_vector.length
            if speed_per_frame == 0:
                return unit.position
            unit_speed = min(speed_per_frame * 22.4, max_speed)
            forward_unit_vector = frame_vector.normalized
        else:
            unit_speed = max_speed
            forward_unit_vector = self.apply_rotation(unit.facing, Point2([0, 1]))

        remaining_distance = unit_speed * seconds_ahead
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

    def distance(self, unit1: Unit, unit2: Unit) -> float:
        try:
            return unit1.distance_to(unit2)
        except IndexError:
            logger.debug(f"cached distance error on {unit1} ({unit1.game_loop}), {unit2}({unit2.game_loop})")
            return unit1.distance_to(unit2.position)

    def closest_distance(self, unit1: Unit, units: Units) -> float:
        distance = 9999
        for unit in units:
            distance = min(distance, self.distance(unit1, unit))
        return distance

    def closest_unit(self, unit1: Unit, units: Units) -> float:
        closest_distance = 9999
        closest_unit = None
        for unit in units:
            new_distance = self.distance(unit1, unit)
            if new_distance < closest_distance:
                closest_distance = new_distance
                closest_unit = unit
        return closest_unit


class TimerMixin:
    def start_timer(self, timer_name: str) -> None:
        if not hasattr(self, "timers"):
            self.timers = {}
        if timer_name not in self.timers:
            self.timers[timer_name] = {"start": perf_counter(), 'total': 0}
        else:
            self.timers[timer_name]["start"] = perf_counter()

    def stop_timer(self, timer_name: str) -> None:
        timer = self.timers[timer_name]
        timer['total'] += perf_counter() - timer["start"]

    def print_timers(self, prefix: str = '') -> None:
        for timer_name in self.timers.keys():
            timer = self.timers[timer_name]
            logger.debug(f"{prefix}{timer_name} execution time: {timer['total']}")


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
