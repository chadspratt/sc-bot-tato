from __future__ import annotations
from typing import Dict

from loguru import logger
from sc2.unit import Unit
from sc2.position import Point2

from .base_squad import BaseSquad


NEARBY_THRESHOLD = 5


class EnemySquad(BaseSquad):
    def __init__(
        self,
        number: int = 0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "enemy" + str(number)
        self.last_seen_time_by_unit_tag: Dict[int, int] = {}
        self.last_known_position: Point2 = None

    def update_references(self):
        self.units = self.get_updated_unit_references_by_tags(
            list(self.units.tags)
        )

    def near(self, unit: Unit, predicted_position: dict[int, Point2]) -> bool:
        for squad_unit in self.units:
            target_position = squad_unit.position
            if squad_unit.tag in predicted_position:
                target_position = predicted_position[squad_unit.tag]
            if unit.distance_to(target_position) < NEARBY_THRESHOLD:
                return True
        return False

    def recruit(self, unit: Unit):
        logger.info(f"adding {unit} into {self.name} squad")
        self.units.append(unit)
