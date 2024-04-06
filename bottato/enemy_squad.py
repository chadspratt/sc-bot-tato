from __future__ import annotations
from typing import Dict

from loguru import logger
from sc2.unit import Unit
from sc2.position import Point2

from .squad import BaseSquad


NEARBY_THRESHOLD = 5


class EnemySquad(BaseSquad):
    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.name = "enemy"
        self.last_seen_time_by_unit_tag: Dict[int, int]
        self.last_known_position: Point2 = None

    def update_references(self):
        self.units = self.get_updated_unit_references_by_tags(
            self.last_seen_time_by_unit_tag.keys()
        )

    def near(self, unit: Unit) -> bool:
        return len(self.units.closer_than(NEARBY_THRESHOLD, unit)) > 0

    def recruit(self, unit: Unit):
        logger.info(f"adding {unit} into {self.name} squad")
        self.units.append(unit)

    def get_report(self) -> str:
        composition = {}
        for unit in self.units:
            composition.setdefault(unit.type_id, []).append(unit)
        buffer = ""
        for unit_type_id, units in composition.items():
            buffer += f"{unit_type_id}: {len(units)}, "
        return buffer
