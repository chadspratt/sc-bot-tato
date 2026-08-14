from typing import Dict, Tuple

import sc2.position
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.unit import Unit
from sc2.units import Units

from bottato.enums import UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import timed_async
from bottato.unit_types import UnitTypes


class CycloneMicro(BaseUnitMicro):
    lock_on_targets: Dict[int, int] = {}  # unit tag -> target tag

    def __init__(self, bot):
        super().__init__(bot)

    @staticmethod
    async def update_lock_on_states(bot):
        await UnitTypes.update_cyclone_lockon_state(bot, CycloneMicro.lock_on_targets)
        
    @timed_async
    async def _attack_something(self, unit: Unit, health_threshold: float, move_position: sc2.position.Point2, force_move: bool = False) -> UnitMicroType:
        # verify existing lock
        if unit.tag in self.lock_on_targets:
            target_tag = self.lock_on_targets[unit.tag]
            target = self.bot.all_enemy_units.find_by_tag(target_tag)
            # maintain target if locked on
            if target and self.is_locked_onto(target):
                return await self._kite(unit, target)
            else:
                del self.lock_on_targets[unit.tag]

        # handle if a new lock was acquired
        if unit.orders:
            first_order = unit.orders[0]
            if first_order.ability.id == AbilityId.ATTACK and isinstance(first_order.target, int):
                attack_target = self.bot.all_enemy_units.find_by_tag(first_order.target)
                if attack_target and self.is_locked_onto(attack_target):
                    self.lock_on_targets[unit.tag] = attack_target.tag
                    return await self._kite(unit, attack_target)

        # no lock, attack normally
        return await super()._attack_something(unit, health_threshold, move_position, force_move)
    
    def is_locked_onto(self, unit: Unit) -> bool:
        return BuffId.LOCKON in unit.buffs