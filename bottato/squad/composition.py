from typing import Dict, List

from sc2.ids.unit_typeid import UnitTypeId


class Composition():
    def __init__(self, unit_counts: Dict[UnitTypeId, int]) -> None:
        self.unit_counts = unit_counts
        self.unit_ids: List[UnitTypeId] = []
        for unit_id in unit_counts:
            for x in range(unit_counts[unit_id]):
                self.unit_ids.append(unit_id)

    def count_type(self, type: UnitTypeId) -> int:
        return self.unit_counts[type]
