from __future__ import annotations

from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bottato.unit_types import UnitTypes
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin


class BansheeMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.58

    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if await self.bot.can_cast(unit, AbilityId.BEHAVIOR_CLOAKON_BANSHEE) and self.enemy.threats_to(unit):
            unit(AbilityId.BEHAVIOR_CLOAKON_BANSHEE)

    excluded_enemy_types = [
        UnitTypeId.LARVA,
        UnitTypeId.EGG
    ]
    target_structure_types = [
        UnitTypeId.SPINECRAWLER,
    ]
    def _attack_something(self, unit: Unit, health_threshold: float, force_move: bool = False) -> bool:
        if unit.health_percentage < health_threshold:
            return False
        nearby_enemies = self.bot.enemy_units.closer_than(15, unit) + self.bot.enemy_structures.of_type(self.offensive_structure_types).closer_than(15, unit)
        nearby_structures = self.bot.enemy_structures.closer_than(15, unit)
        targets = nearby_enemies.filter(lambda u: not u.is_flying and u.type_id not in self.excluded_enemy_types)
        tanks: Units = targets.filter(lambda u: u.type_id in (UnitTypeId.SIEGETANKSIEGED, UnitTypeId.SIEGETANK))
        if not targets:
            targets = nearby_structures
        threats = nearby_enemies.filter(lambda u: UnitTypes.can_attack_air(u))
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if targets:
            if not threats:
                if tanks:
                    unit.attack(tanks.closest_to(unit))
                else:
                    unit.attack(targets.closest_to(unit))
                return True
            elif can_attack and len(threats) < 4:
                attackable_threats = threats.filter(lambda u: not u.is_flying) + tanks
                if attackable_threats:
                    unit.attack(attackable_threats.closest_to(unit))
                else:
                    unit.attack(targets.closest_to(unit))
                return True
            if self._retreat_to_tank(unit, can_attack):
                return True
            if self._stay_at_max_range(unit, threats):
                return True
        return False
