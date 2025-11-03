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

    def get_updated_unit_reference(self, unit: Unit, units_by_tag: dict[int, Unit] = None) -> Unit:
        if unit is None:
            raise self.UnitNotFound(
                "unit is None"
            )
        return self.get_updated_unit_reference_by_tag(unit.tag, units_by_tag)

    def get_updated_unit_reference_by_tag(self, tag: int, units_by_tag: dict[int, Unit]) -> Unit:
        try:
            if units_by_tag is None:
                # used for events outside of on_step
                return self.bot.all_units.by_tag(tag)
            return units_by_tag[tag]
        except KeyError:
            raise self.UnitNotFound(
                f"Cannot find unit with tag {tag}; maybe they died"
            )

    def get_updated_unit_references(self, units: Units, units_by_tag: dict[int, Unit] = None) -> Units:
        _units = Units([], bot_object=self.bot)
        for unit in units:
            try:
                _units.append(self.get_updated_unit_reference(unit, units_by_tag))
            except self.UnitNotFound:
                logger.debug(f"Couldn't find unit {unit}!")
        return _units

    def get_updated_unit_references_by_tags(self, tags: List[int], units_by_tag: dict[int, Unit] = None) -> Units:
        _units = Units([], bot_object=self.bot)
        for tag in tags:
            try:
                _units.append(self.get_updated_unit_reference_by_tag(tag, units_by_tag))
            except self.UnitNotFound:
                logger.debug(f"Couldn't find unit {tag}!")
        return _units

    def count_units_by_type(self, units: Units, use_common_type=True) -> dict[UnitTypeId, int]:
        counts: dict[UnitTypeId, int] = {}

        for unit in units:
            type_id = unit.unit_alias if use_common_type and unit.unit_alias else unit.type_id
            # passenger units don't have this attribute
            if hasattr(unit, "is_hallucination") and unit.is_hallucination:
                continue
            if type_id not in counts:
                counts[type_id] = 1
            else:
                counts[type_id] += 1

        return counts

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
        height: float = max(0, self.bot.get_terrain_z_height(point2) + 1)
        return Point3((point2.x, point2.y, height))

    def get_facing(self, start_position: Unit | Point2, end_position: Unit | Point2):
        start_position = start_position.position
        end_position = end_position.position
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
        if frame_vector is not None:
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
        if unit1 is None or unit2 is None:
            return 9999
        try:
            return unit1.distance_to(unit2)
        except IndexError:
            logger.debug(f"cached distance error on {unit1} ({unit1.game_loop}), {unit2}({unit2.game_loop})")
            return unit1.distance_to(unit2.position)
        
    def distance_squared(self, unit1: Unit, unit2: Unit) -> float:
        if unit1 is None or unit2 is None:
            return 9999
        try:
            return unit1.distance_to_squared(unit2)
        except IndexError:
            logger.debug(f"cached distance error on {unit1} ({unit1.game_loop}), {unit2}({unit2.game_loop})")
            return unit1.distance_to_squared(unit2.position)

    def closest_distance(self, unit1: Unit, units: Units) -> float:
        distance = 9999
        for unit in units:
            distance = min(distance, self.distance(unit1, unit))
        return distance
    
    def closest_distance_squared(self, unit1: Unit, units: Units) -> float:
        closest_distance_sq = 9999
        for unit in units:
            closest_distance_sq = min(closest_distance_sq, self.distance_squared(unit1, unit))
        return closest_distance_sq

    def closest_unit_to_unit(self, unit1: Unit, units: Units) -> float:
        closest_distance = 9999
        closest_unit = None
        for unit in units:
            new_distance = self.distance(unit1, unit)
            if new_distance < closest_distance:
                closest_distance = new_distance
                closest_unit = unit
        return closest_unit

    def get_triangle_point_c(self, point_a: Point2, point_b: Point2, a_c_distance: float, b_c_distance: float) -> tuple[Point2, Point2]:
        a_b_distance = point_a.distance_to(point_b)
        if a_b_distance > a_c_distance + b_c_distance or a_c_distance > a_b_distance + b_c_distance or b_c_distance > a_b_distance + a_c_distance:
            return None
        a_b_distance_sq = a_b_distance ** 2
        a_c_distance_sq = a_c_distance ** 2
        b_c_distance_sq = b_c_distance ** 2
        angle_a = math.acos((a_c_distance_sq + a_b_distance_sq - b_c_distance_sq) / (2 * a_b_distance * a_c_distance))
        a_b_facing = self.get_facing(point_a, point_b)
        angle_1 = a_b_facing + angle_a
        angle_2 = a_b_facing - angle_a
        point_c_1 = point_a + Point2((math.cos(angle_1), math.sin(angle_1))) * a_c_distance
        point_c_2 = point_a + Point2((math.cos(angle_2), math.sin(angle_2))) * a_c_distance
        return point_c_1, point_c_2

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
        if hasattr(self, "timers"):
            for timer_name in self.timers.keys():
                timer = self.timers[timer_name]
                logger.info(f"{prefix}{timer_name} execution time: {timer['total']}")


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
