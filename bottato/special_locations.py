from loguru import logger
from typing import List

from sc2.ids.unit_typeid import UnitTypeId
from sc2.game_info import Ramp
from sc2.position import Point2


class SpecialLocation:
    def __init__(self, unit_type_id: UnitTypeId, position: Point2):
        self.is_started: bool = False
        self.is_complete: bool = False
        self.unit_tag: int | None = None
        self.unit_type_id = unit_type_id
        self.position = position
        logger.debug(f"Will build {unit_type_id} at {position} to block ramp")

    def __eq__(self, other):
        return self.unit_type_id == other.type_id and self.position == other.position


class SpecialLocations:
    def __init__(self, ramp: Ramp):
        self.is_blocked: bool = False
        self.ramps = []
        self.ramp_blockers = []
        self.add_ramp(ramp)

    def add_ramp(self, ramp: Ramp):
        ramp_blockers: List[SpecialLocation] = []
        for corner_position in ramp.corner_depots:
            ramp_blockers.append(SpecialLocation(UnitTypeId.SUPPLYDEPOT, corner_position))
        ramp_blockers.append(
            SpecialLocation(UnitTypeId.BARRACKS, ramp.barracks_correct_placement)
        )
        self.ramp_blockers.extend(ramp_blockers)

    def find_placement(self, unit_type_id: UnitTypeId) -> Point2:
        for ramp_blocker in self.ramp_blockers:
            if ramp_blocker.is_started:
                continue
            if unit_type_id == ramp_blocker.unit_type_id:
                return ramp_blocker.position
        return None
