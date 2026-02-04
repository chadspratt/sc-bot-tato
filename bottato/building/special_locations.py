from loguru import logger
from typing import List

from sc2.bot_ai import BotAI
from sc2.game_info import Ramp
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit


class SpecialLocation:
    def __init__(self, unit_type_id: UnitTypeId, position: Point2):
        self.is_started: bool = False
        self.is_complete: bool = False
        self.unit_tag: int | None = None
        self.unit_type_id = unit_type_id
        self.position = position
        logger.debug(f"Will build {unit_type_id} at {position} to block ramp")

    def __eq__(self, other: object) -> bool:
        assert isinstance(other, Unit)
        return self.unit_type_id == other.type_id and self.position == other.position


class SpecialLocations:
    def __init__(self, ramp: Ramp):
        self.is_blocked: bool = False
        self.ramps = []
        self.ramp_blockers: List[SpecialLocation] = []
        self.add_ramp(ramp)

    def add_ramp(self, ramp: Ramp):
        ramp_blockers: List[SpecialLocation] = []
        for corner_position in ramp.corner_depots:
            ramp_blockers.append(SpecialLocation(UnitTypeId.SUPPLYDEPOT, corner_position))
        ramp_blockers.append(
            SpecialLocation(UnitTypeId.BARRACKS, ramp.barracks_in_middle) # type: ignore
        )
        self.ramp_blockers.extend(ramp_blockers)

    def find_placement(self, unit_type_id: UnitTypeId) -> Point2 | None:
        for ramp_blocker in self.ramp_blockers:
            if ramp_blocker.is_started:
                continue
            if unit_type_id == ramp_blocker.unit_type_id:
                return ramp_blocker.position
        return None
    
    @staticmethod
    async def get_bunker_positions(bot: BotAI) -> List[Point2]:
        barracks_position: Point2 = bot.main_base_ramp.barracks_correct_placement # type: ignore
        ramp_bottom_center = bot.main_base_ramp.bottom_center
        candidates: List[Point2] = []
        if barracks_position.x < ramp_bottom_center.x:
            # ramp goes right
            if barracks_position.y < ramp_bottom_center.y:
                # ramp goes up
                candidates = [
                    barracks_position + Point2((-2, 3)),
                    barracks_position + Point2((3, -3)),
                ]
            else:
                # ramp goes down
                candidates = [
                    barracks_position + Point2((4, 3)),
                    barracks_position + Point2((-1, -3)),
                ]
        else:
            # ramp goes left
            if barracks_position.y < ramp_bottom_center.y:
                # ramp goes up
                candidates = [
                    barracks_position + Point2((3, 2)),
                    barracks_position + Point2((-1, -3)),
                ]
            else:
                # ramp goes down
                preferred_right = barracks_position + Point2((3, -3))
                if await bot.can_place_single(UnitTypeId.BUNKER, preferred_right):
                    candidates = [
                        barracks_position + Point2((-2, 3)),
                        preferred_right,
                    ]
                else:
                    candidates = [
                        barracks_position + Point2((-2, 3)),
                        barracks_position + Point2((5, -2)),
                    ]
        return candidates
