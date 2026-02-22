import math
import random
from functools import wraps
from loguru import logger
from time import perf_counter
from typing import Dict, List

from cython_extensions import cy_distance_to_squared
from cython_extensions.geometry import cy_distance_to
from cython_extensions.units_utils import cy_closer_than
from sc2.bot_ai import BotAI
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.units import Units

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
    timing_message = "Timing Results:"
    for func_name, total_time in sorted(_decorator_timers.items(), key=lambda x: x[1], reverse=True):
        timing_message += f"\n{func_name},{total_time:.4f},{_decorator_timer_counts[func_name]}"
    logger.info(timing_message)


class GeometryMixin:
    @staticmethod
    def convert_point2_to_3(point2: Point2 | Unit, bot: BotAI) -> Point3:
        if isinstance(point2, Unit):
            point2 = point2.position
        height: float = max(0, bot.get_terrain_z_height(point2) + 1)
        return Point3((point2.x, point2.y, height))
    
    @staticmethod
    def clamp_position_to_map_bounds(position: Point2, origin: Point2, bot: BotAI) -> Point2:
        clamped_x = max(0, min(position.x, bot.game_info.terrain_height.width))
        clamped_y = max(0, min(position.y, bot.game_info.terrain_height.height))
        excess_x = abs(position.x - clamped_x)
        excess_y = abs(position.y - clamped_y)
        if excess_x > 0 and excess_y > 0:
            if excess_x > excess_y:
                # turn away from the corner
                if origin.y < position.y:
                    clamped_y = origin.y - excess_x
                else:
                    clamped_y = origin.y + excess_x
            else:
                if origin.x < position.x:
                    clamped_x = origin.x - excess_y
                else:
                    clamped_x = origin.x + excess_y
        elif excess_x > 0:
            if origin.y < position.y:
                clamped_y += excess_x
            else:
                clamped_y -= excess_x
            # add excess to other axis to move along the edge
        elif excess_y > 0:
            if origin.x < position.x:
                clamped_x += excess_y
            else:
                clamped_x -= excess_y

        clamped_position = Point2((
            clamped_x,
            clamped_y
        ))
        return clamped_position

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
    def get_vector_towards_biggest_gap(unit_position: Point2, enemy_positions: List[Point2]) -> Point2:
        angles = sorted([GeometryMixin.get_facing(unit_position, enemy_pos) for enemy_pos in enemy_positions])
        angles.append(angles[0] + 2 * math.pi)  # wrap around for circular comparison
        biggest_gap = 0
        best_facing = 0
        for i in range(len(angles) - 1):
            gap = angles[i + 1] - angles[i]
            if gap > biggest_gap:
                biggest_gap = gap
                best_facing = (angles[i] + angles[i + 1]) / 2 % (2 * math.pi)
        return Point2((math.cos(best_facing), math.sin(best_facing)))

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
    def distance(unit1: Unit | Point2, unit2: Unit | Point2, predicted_positions: Dict[int, Point2] | None = None) -> float:
        if predicted_positions is not None:
            if isinstance(unit1, Unit) and unit1.age != 0:
                try:
                    unit1 = predicted_positions[unit1.tag]
                except KeyError:
                    pass
            if isinstance(unit2, Unit) and unit2.age != 0:
                try:
                    unit2 = predicted_positions[unit2.tag]
                except KeyError:
                    pass
        return cy_distance_to(unit1.position, unit2.position)
        
    @staticmethod
    def distance_squared(unit1: Unit | Point2, unit2: Unit | Point2) -> float:
        if isinstance(unit1, Unit) and isinstance(unit2, Unit) and unit1.age == 0 and unit2.age == 0:
            return unit1.distance_to_squared(unit2)
        return cy_distance_to_squared(unit1.position, unit2.position)

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
    def units_closer_than(unit1: Unit | Point2, units: Units, distance: float, bot: BotAI) -> Units:
        close_units: Units = Units([], bot_object=bot)
        distance_sq = distance * distance
        for unit in units:
            if GeometryMixin.distance_squared(unit1, unit) < distance_sq:
                close_units.append(unit)
        return close_units
    
    @staticmethod
    def member_is_closer_than(unit1: Unit | Point2, units: Units | List[Point2 | Unit], distance: float) -> bool:
        distance_sq = distance * distance
        for unit in units:
            if GeometryMixin.distance_squared(unit1, unit) < distance_sq:
                return True
        return False

    @staticmethod
    def closest_unit_to_unit(unit1: Unit | Point2, units: Units, predicted_positions: Dict[int, Point2] | None = None) -> Unit:
        assert units, "units list is empty"
        closest_distance = 9999
        closest_unit: Unit = units[0]
        for unit in units:
            new_distance = GeometryMixin.distance(unit1, unit, predicted_positions)
            if new_distance < closest_distance:
                closest_distance = new_distance
                closest_unit = unit
        return closest_unit

    @staticmethod
    def get_triangle_point_c(point_a: Point2, point_b: Point2, a_c_distance: float, b_c_distance: float) -> tuple[Point2, Point2] | None:
        a_b_distance = cy_distance_to(point_a, point_b)
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
        most_nearby_units: List[Unit] = [units[0]]
        for unit in units:
            nearby_units = cy_closer_than(units, range, unit.position)
            if len(nearby_units) > len(most_nearby_units):
                most_nearby_unit = unit
                most_nearby_units = nearby_units
        return (most_nearby_unit, Units(most_nearby_units, bot_object=bot))
    
    @staticmethod
    def position_is_between(point: Point2, point_a: Point2, point_b: Point2) -> bool:
        ab_distance = cy_distance_to_squared(point_a, point_b)
        ap_distance = cy_distance_to_squared(point_a, point)
        pb_distance = cy_distance_to_squared(point, point_b)
        return ap_distance < ab_distance and pb_distance < ab_distance 
    
    def vectors_go_same_direction(self, vec1: Point2, vec2: Point2) -> bool:
        dot_product = vec1.x * vec2.x + vec1.y * vec2.y
        return dot_product > 0


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
