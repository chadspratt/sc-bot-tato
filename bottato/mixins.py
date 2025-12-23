import math
import random
from loguru import logger
from typing import Dict, List
from time import perf_counter
from functools import wraps

from sc2.bot_ai import BotAI
from sc2.game_data import Cost
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3

from bottato.log_helper import LogHelper


# Global timer storage for decorator
_decorator_timers: Dict[str, float] = {}
_decorator_timer_counts: Dict[str, int] = {}


def timed(func):
    """Decorator to automatically time function execution and accumulate total time."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = perf_counter()
        result = func(*args, **kwargs)
        elapsed = perf_counter() - start
        
        log_decorator_timer(*args, func=func, elapsed=elapsed)
        
        return result
    return wrapper


def timed_async(func):
    """Decorator to automatically time async function execution and accumulate total time."""
    @wraps(func)
    async def wrapper(*args, **kwargs):
        start = perf_counter()
        result = await func(*args, **kwargs)
        elapsed = perf_counter() - start
        
        log_decorator_timer(*args, func=func, elapsed=elapsed)
        
        return result
    return wrapper

def log_decorator_timer(*args, func, elapsed: float):
    """Log elapsed time for a decorated function."""
    # Include class name if this is a method
    if args and hasattr(args[0], '__class__'):
        func_name = f"{args[0].__class__.__name__}.{func.__name__}"
    else:
        func_name = func.__name__

    try:
        _decorator_timers[func_name] += elapsed
        _decorator_timer_counts[func_name] += 1
    except KeyError:
        _decorator_timers[func_name] = elapsed
        _decorator_timer_counts[func_name] = 1


def print_decorator_timers():
    """Print all accumulated timer data from @timed decorators."""
    timing_message = "Decorator Timing Results:"
    for func_name, total_time in sorted(_decorator_timers.items(), key=lambda x: x[1], reverse=True):
        timing_message += f"\n{func_name},{total_time:.4f},{_decorator_timer_counts[func_name]}"
    logger.info(timing_message)


class UnitReferenceMixin:
    class UnitNotFound(Exception):
        pass

    def get_updated_unit_reference(self, unit: Unit | None, bot: BotAI, units_by_tag: dict[int, Unit] | None = None) -> Unit:
        if unit is None:
            raise self.UnitNotFound(
                "unit is None"
            )
        return self.get_updated_unit_reference_by_tag(unit.tag, bot, units_by_tag)

    def get_updated_unit_reference_by_tag(self, tag: int, bot: BotAI, units_by_tag: dict[int, Unit] | None = None) -> Unit:
        try:
            if units_by_tag is None:
                # used for events outside of on_step
                return bot.all_units.by_tag(tag)
            return units_by_tag[tag]
        except KeyError:
            raise self.UnitNotFound(
                f"Cannot find unit with tag {tag}; maybe they died"
            )

    def get_updated_unit_references(self, units: Units, bot: BotAI, units_by_tag: dict[int, Unit] | None = None) -> Units:
        _units = Units([], bot_object=bot)
        for unit in units:
            try:
                _units.append(self.get_updated_unit_reference(unit, bot, units_by_tag))
            except self.UnitNotFound:
                logger.debug(f"Couldn't find unit {unit}!")
        return _units

    def get_updated_unit_references_by_tags(self, tags: List[int], bot: BotAI, units_by_tag: dict[int, Unit] | None = None) -> Units:
        _units = Units([], bot_object=bot)
        for tag in tags:
            try:
                _units.append(self.get_updated_unit_reference_by_tag(tag, bot, units_by_tag))
            except self.UnitNotFound:
                logger.debug(f"Couldn't find unit {tag}!")
        return _units

    def get_army_value(self, units: Units, bot: BotAI) -> float:
        army_value: float = 0
        type_costs: Dict[UnitTypeId, float] = {}
        for unit in units:
            if unit.is_structure:
                continue
            if unit.type_id not in type_costs:
                try:
                    cost: Cost = bot.calculate_cost(unit.type_id)
                except AttributeError:
                    continue
                supply = bot.calculate_supply_cost(unit.type_id)
                type_costs[unit.type_id] = ((cost.minerals * 0.9) + cost.vespene) * supply
            army_value += type_costs[unit.type_id]
        return army_value


class GeometryMixin:
    @staticmethod
    def convert_point2_to_3(point2: Point2 | Unit, bot: BotAI) -> Point3:
        if isinstance(point2, Unit):
            point2 = point2.position
        height: float = max(0, bot.get_terrain_z_height(point2) + 1)
        return Point3((point2.x, point2.y, height))

    @staticmethod
    def get_facing(start_position: Unit | Point2, end_position: Unit | Point2):
        if isinstance(start_position, Unit):
            start_position = start_position.position
        if isinstance(end_position, Unit):
            end_position = end_position.position
        angle = math.atan2(
            end_position.y - start_position.y, end_position.x - start_position.x
        )
        if angle < 0:
            angle += math.pi * 2
        return angle

    @staticmethod
    def apply_rotation(angle: float, point: Point2, reverse_direction: bool = False) -> Point2:
        # rotations default to facing along the y-axis, with a facing of pi/2
        logger.debug(f"apply_rotation at angle {angle}")
        rotation_needed = math.pi / 2 - angle if reverse_direction else angle - math.pi / 2

        logger.debug(f">> adjusted to {rotation_needed}")
        s_theta = math.sin(rotation_needed)
        c_theta = math.cos(rotation_needed)
        rotated = GeometryMixin._apply_rotation(s_theta=s_theta, c_theta=c_theta, point=point)
        logger.debug(f"rotation calculated from {point} to {rotated}")
        return rotated

    @staticmethod
    def _apply_rotation(*, s_theta: float, c_theta: float, point: Point2) -> Point2:
        new_x = point.x * c_theta - point.y * s_theta
        new_y = point.x * s_theta + point.y * c_theta
        return Point2((new_x, new_y))

    @staticmethod
    @timed
    def apply_rotations(angle: float, points: List[Point2] | None=None) -> List[Point2]:
        # rotations default to facing along the y-axis, with a facing of pi/2
        if points is None:
            return []
        rotation_needed = angle - math.pi / 2
        s_theta = math.sin(rotation_needed)
        c_theta = math.cos(rotation_needed)
        return [
            GeometryMixin._apply_rotation(s_theta=s_theta, c_theta=c_theta, point=point) for point in points
        ]

    @staticmethod
    def predict_future_unit_position(unit: Unit,
                                     seconds_ahead: float,
                                     bot: BotAI,
                                     check_pathable: bool = True,
                                     frame_vector: Point2 | None = None
                                     ) -> Point2:
        if unit.is_structure:
            return unit.position
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
            forward_unit_vector = GeometryMixin.apply_rotation(unit.facing, Point2([0, 1]))

        remaining_distance = unit_speed * seconds_ahead
        if not check_pathable:
            return unit.position + forward_unit_vector * remaining_distance

        future_position = unit.position
        while True:
            if remaining_distance < 1:
                forward_unit_vector *= remaining_distance
            potential_position = future_position + forward_unit_vector
            if not bot.in_pathing_grid(potential_position):
                return future_position

            future_position = potential_position

            remaining_distance -= 1
            if remaining_distance <= 0:
                return future_position

    @staticmethod
    def distance(unit1: Unit, unit2: Unit) -> float:
        if unit1.age == 0 and unit2.age == 0:
            return unit1.distance_to(unit2)
        return unit1.distance_to(unit2.position)
        
    @staticmethod
    @timed
    def distance_squared(unit1: Unit | Point2, unit2: Unit | Point2, predicted_positions: Dict[int, Point2] | None = None) -> float:
        if isinstance(unit1, Unit) and unit1.age != 0 and predicted_positions is not None:
            try:
                unit1 = predicted_positions[unit1.tag]
            except KeyError:
                pass
        if isinstance(unit2, Unit) and unit2.age != 0 and predicted_positions is not None:
            try:
                unit2 = predicted_positions[unit2.tag]
            except KeyError:
                pass
        if isinstance(unit1, Point2):
            if isinstance(unit2, Point2):
                return unit1._distance_squared(unit2)
            return unit1._distance_squared(unit2.position)
        if isinstance(unit2, Point2):
            return unit1.position._distance_squared(unit2)
        if unit1.age == 0 and unit2.age == 0:
            return unit1.distance_to_squared(unit2)        
        return unit1.distance_to_squared(unit2.position)

    @staticmethod
    def closest_distance(unit1: Unit, units: Units) -> float:
        distance = 9999
        for unit in units:
            distance = min(distance, GeometryMixin.distance_squared(unit1, unit))
        return distance ** 0.5
    
    @staticmethod
    def closest_distance_squared(unit1: Unit | Point2, units: Units) -> float:
        closest_distance_sq = 9999
        for unit in units:
            closest_distance_sq = min(closest_distance_sq, GeometryMixin.distance_squared(unit1, unit))
        return closest_distance_sq
    
    @staticmethod
    def units_closer_than(unit1: Unit, units: Units, distance: float, bot: BotAI) -> Units:
        close_units: Units = Units([], bot_object=bot)
        distance_sq = distance * distance
        for unit in units:
            if GeometryMixin.distance_squared(unit1, unit) < distance_sq:
                close_units.append(unit)
        return close_units
    
    @staticmethod
    def unit_is_closer_than(unit1: Unit, units: Units, distance: float, bot: BotAI) -> bool:
        distance_sq = distance * distance
        for unit in units:
            if GeometryMixin.distance_squared(unit1, unit) < distance_sq:
                return True
        return False

    @staticmethod
    def closest_unit_to_unit(unit1: Unit, units: Units) -> Unit:
        assert units, "units list is empty"
        closest_distance = 9999
        closest_unit: Unit = units[0]
        for unit in units:
            new_distance = GeometryMixin.distance(unit1, unit)
            if new_distance < closest_distance:
                closest_distance = new_distance
                closest_unit = unit
        return closest_unit

    @staticmethod
    def get_triangle_point_c(point_a: Point2, point_b: Point2, a_c_distance: float, b_c_distance: float) -> tuple[Point2, Point2] | None:
        a_b_distance = point_a.distance_to(point_b)
        if a_b_distance > a_c_distance + b_c_distance or a_c_distance > a_b_distance + b_c_distance or b_c_distance > a_b_distance + a_c_distance:
            return None
        a_b_distance_sq = a_b_distance ** 2
        a_c_distance_sq = a_c_distance ** 2
        b_c_distance_sq = b_c_distance ** 2
        angle_a = math.acos((a_c_distance_sq + a_b_distance_sq - b_c_distance_sq) / (2 * a_b_distance * a_c_distance))
        a_b_facing = GeometryMixin.get_facing(point_a, point_b)
        angle_1 = a_b_facing + angle_a
        angle_2 = a_b_facing - angle_a
        point_c_1 = point_a + Point2((math.cos(angle_1), math.sin(angle_1))) * a_c_distance
        point_c_2 = point_a + Point2((math.cos(angle_2), math.sin(angle_2))) * a_c_distance
        return point_c_1, point_c_2
    
    @staticmethod
    def get_most_grouped_unit(units: Units, bot: BotAI, range: float = 10) -> tuple[Unit, Units]:
        assert units, "units list is empty"
        most_nearby_unit: Unit = units[0]
        most_nearby_units: Units = Units([], bot_object=bot)
        for unit in units:
            nearby_units = units.filter(lambda u: u.position.manhattan_distance(unit.position) < range)
            if nearby_units.amount > most_nearby_units.amount:
                most_nearby_unit = unit
                most_nearby_units = nearby_units
        return (most_nearby_unit, most_nearby_units)
    
    @staticmethod
    def position_is_between(point: Point2, point_a: Point2, point_b: Point2) -> bool:
        ab_distance = point_a._distance_squared(point_b)
        ap_distance = point_a._distance_squared(point)
        pb_distance = point._distance_squared(point_b)
        return ap_distance < ab_distance and pb_distance < ab_distance 


class DebugMixin:
    @staticmethod
    def random_color() -> tuple[int, int, int]:
        rgb = [0, 0, 0]
        highlow_index = random.randint(0, 2)
        high_or_low = random.randint(0, 1) > 0
        for i in range(3):
            if i == highlow_index:
                rgb[i] = 255 if high_or_low else 0
            else:
                rgb[i] = random.randint(0, 255)
        return (rgb[0], rgb[1], rgb[2])
