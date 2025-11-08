from __future__ import annotations
from loguru import logger

from sc2.position import Point2
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId

from .base_unit_micro import BaseUnitMicro
from sc2.ids.ability_id import AbilityId
from ..enemy import Enemy
from ..mixins import GeometryMixin


class VikingMicro(BaseUnitMicro, GeometryMixin):
    turret_drop_range = 2
    turret_attack_range = 6
    ideal_enemy_distance = turret_drop_range + turret_attack_range - 1
    # XXX use shorter range if enemy unit is facing away from raven, likely fleeing
    turret_energy_cost = 50
    ability_health = 0.6
    turret_drop_time = 1.5

    async def use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        nearby_enemies = self.bot.enemy_units.closer_than(15, unit.position)
        if unit.is_flying:
            if unit.health_percentage >= health_threshold:
                # land on enemy sieged tanks
                if len(nearby_enemies) == 1 and nearby_enemies[0].type_id == UnitTypeId.SIEGETANKSIEGED:
                    nearest_tank: Unit = nearby_enemies[0]
                    if unit.distance_to(nearest_tank) > 1.8:
                        unit.move(nearest_tank.position)
                    elif unit.distance_to(nearest_tank) < 1.1:
                        unit.move(unit.position.towards(nearest_tank, -1.2))
                    else:
                        unit(AbilityId.MORPH_VIKINGASSAULTMODE)
                    return True
        else:
            if len(nearby_enemies) != 1 or unit.health_percentage < health_threshold:
                # take off if multiple or no enemies nearby
                unit(AbilityId.MORPH_VIKINGFIGHTERMODE)
                return True
            enemy_tank = nearby_enemies.filter(lambda u: u.type_id == UnitTypeId.SIEGETANKSIEGED)
            if enemy_tank:
                unit.attack(enemy_tank)
                return True
        return False