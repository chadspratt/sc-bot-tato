from __future__ import annotations

from loguru import logger
from typing import Dict

from cython_extensions.geometry import cy_distance_to
from sc2.position import Point2
from sc2.unit import Unit

from bottato.squad.squad import Squad

NEARBY_THRESHOLD = 5


class EnemySquad(Squad):
    def __init__(
        self,
        number: int = 0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "enemy" + str(number)
        self.last_seen_time_by_unit_tag: Dict[int, int] = {}
        self.last_known_position: Point2 | None = None

    def near(self, unit: Unit, predicted_position: dict[int, Point2]) -> bool:
        for squad_unit in self.units:
            target_position = squad_unit.position
            if squad_unit.tag in predicted_position:
                target_position = predicted_position[squad_unit.tag]
            if cy_distance_to(unit.position, target_position) < NEARBY_THRESHOLD:
                return True
        return False

    def recruit(self, new_unit: Unit):
        logger.debug(f"adding {new_unit} into {self.name} squad")
        self.units.append(new_unit)
