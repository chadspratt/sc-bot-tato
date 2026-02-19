from __future__ import annotations

from cython_extensions.units_utils import cy_closer_than
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.enums import UnitAttribute, UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import timed_async
from bottato.unit_types import UnitTypes


class ThorMicro(BaseUnitMicro):
    # Unit types where High Impact Mode deals significantly more damage (armored/massive air)
    MASSIVE_AIR_TYPES = {
        UnitTypeId.COLOSSUS,
        UnitTypeId.CARRIER,
        UnitTypeId.TEMPEST,
        UnitTypeId.MOTHERSHIP,
        UnitTypeId.BATTLECRUISER,
        UnitTypeId.BROODLORD,
    }
    AIR_COUNT_THRESHOLD = 3
    AIR_RANGE = 11  # Thor air attack range + small buffer
    MIN_SECONDS_BETWEEN_TRANSFORM = 3.0
    last_transform_time: dict[int, float] = {}

    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, force_move: bool = False) -> UnitMicroType:
        if unit.is_transforming:
            return UnitMicroType.NONE

        last_transform = self.last_transform_time.get(unit.tag, -self.MIN_SECONDS_BETWEEN_TRANSFORM)
        if self.bot.time - last_transform < self.MIN_SECONDS_BETWEEN_TRANSFORM:
            return UnitMicroType.NONE
        
        is_high_impact = unit.type_id == UnitTypeId.THORAP
        if is_high_impact:
            # transform back to explosive mode if there are no air targets
            air_types = UnitTypes.get_types_with_attribute(UnitAttribute.AIR, self.enemy.enemy_race)
            air_target: Unit | None = self.enemy.get_target_closer_than(unit, 20, included_types=air_types)[0]
            if air_target is None:
                unit(AbilityId.MORPH_THOREXPLOSIVEMODE)
                self.last_transform_time[unit.tag] = self.bot.time
                return UnitMicroType.USE_ABILITY
        else:
            # transform to high impact mode if there are massive air targets
            high_impact_target: Unit | None = self.enemy.get_target_closer_than(unit, 20, included_types=self.MASSIVE_AIR_TYPES)[0]
            wants_high_impact = high_impact_target is not None

            if wants_high_impact:
                unit(AbilityId.MORPH_THORHIGHIMPACTMODE)
                self.last_transform_time[unit.tag] = self.bot.time
                return UnitMicroType.USE_ABILITY

        return UnitMicroType.NONE
