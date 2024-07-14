from __future__ import annotations

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from .base_unit_micro import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class SiegeTankMicro(BaseUnitMicro, GeometryMixin):
    def __init__(self, bot: BotAI):
        super().__init__(bot)

    async def use_ability(self, unit: Unit, enemy: Enemy, health_threshold: float) -> bool:
        enemy_distance = enemy.get_closest_enemy(unit)["distance"]
        if enemy_distance > 7:
            if enemy_distance < 15:
                self.siege(unit)
            else:
                self.unsiege(unit)

    def siege(self, unit: Unit):
        unit(AbilityId.SIEGEMODE_SIEGEMODE)

    def unsiege(self, unit: Unit):
        unit(AbilityId.UNSIEGE_UNSIEGE)
