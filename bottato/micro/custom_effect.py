from sc2.position import Point2
from sc2.unit import Unit

from bottato.enums import CustomEffectType


class CustomEffect:
    def __init__(self, type: CustomEffectType, position: Unit | Point2, radius: float, start_time: float, duration: float):
        self.type: CustomEffectType = type
        self.position = position
        self.radius = radius
        self.start_time = start_time
        self.duration = duration
