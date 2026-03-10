from __future__ import annotations

from typing import Dict, List, Set

from cython_extensions.geometry import cy_distance_to_squared, cy_towards
from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.units import Units

from bottato.enemy import Enemy
from bottato.enums import ExpansionSelection, UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import GeometryMixin, timed_async
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.scouting_location import ScoutingLocation
from bottato.squad.squad import Squad
from bottato.tactics import Tactics
from bottato.unit_types import UnitTypes


class HuntingSquadType():
    def __init__(self, unit_composition: dict[UnitTypeId, int], target_types: Set[UnitTypeId], start_time: float = 0):
        self.unit_composition = unit_composition
        self.target_types = target_types
        self.start_time = start_time
        self.name = f"Hunt {'/'.join([t.name for t in target_types])}"


hunting_squad_types: Dict[Race, List[HuntingSquadType]] = {
    Race.Zerg: [
        HuntingSquadType({UnitTypeId.VIKINGFIGHTER: 1},
                         {UnitTypeId.OVERLORD, UnitTypeId.OVERSEER}, 180),
        HuntingSquadType({UnitTypeId.RAVEN: 1, UnitTypeId.MARINE: 3},
                         {UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORQUEEN}, 300),
    ],
    Race.Terran: [
        HuntingSquadType({UnitTypeId.VIKINGFIGHTER: 1},
                         {UnitTypeId.MEDIVAC}, 240),
    ],
}


class HuntingSquad(Squad, GeometryMixin):
    def __init__(
        self,
        bot: BotAI,
        tactics: Tactics,
        name: str,
        color: tuple[int, int, int]
    ):
        super().__init__(bot, name, color)
        self.tactics = tactics
        self.enemy = tactics.enemy
        self.intel = tactics.intel
        self.units: Units = Units([], bot_object=bot)

        self.next_location: ScoutingLocation | None = None
        self.closest_distance_to_next_location = float('inf')
        self.time_of_closest_distance = 0
        self.had_units = False

    def __repr__(self):
        return f"HuntingSquad({self.name},{len(self.units)})"

    unsafe_targets: Dict[int, float] = {}
    @timed_async
    async def hunt(self, target_types: Set[UnitTypeId]):
        if not self.units:
            return
        self.had_units = True

        targets = self.enemy.get_recent_enemies().filter(lambda u: u.type_id in target_types)
        safe_targets = targets.filter(lambda u: self.bot.time - self.unsafe_targets.get(u.tag, 0) > 20)
        if not safe_targets:     
            safe_targets = targets.filter(lambda u: self.bot.time - self.unsafe_targets.get(u.tag, 0) > 5)
        safe_targets_near_base = safe_targets.filter(lambda u: self.enemy.get_units_closer_than(u, self.bot.structures, 40).exists)
        # safe_targets_near_base = safe_targets.filter(lambda u: self.enemy.get_closest_distance_squared(u, self.bot.structures) < 1600)
        candidates = safe_targets_near_base if safe_targets_near_base else safe_targets

        if candidates:
            self.next_location = None
            self.closest_distance_to_next_location = float('inf')
            target = self.closest_unit_to_unit(self.units.center, candidates)
            for unit in self.units:
                micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
                destination = Point2(cy_towards(target.position, unit.position, UnitTypes.range_vs_target(unit, target) - 0.5))
                if await micro.move(unit, destination) == UnitMicroType.RETREAT:
                    self.unsafe_targets[target.tag] = self.bot.time
        else:
            scout_locations = self.tactics.map.expansion_orders[ExpansionSelection.AWAY_FROM_ENEMY]
            location_count = len(scout_locations) // 2 + 1
            # only hunt on friendly side of map
            self.next_location = sorted(scout_locations[:location_count], key=lambda loc: loc.last_seen)[0]
            for unit in self.units:
                micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
                await micro.harass(unit, self.next_location.scouting_position)

            # mark location as seen if can't get closer for 5 seconds
            distance_to_next_location = cy_distance_to_squared(self.units.center, self.next_location.scouting_position)
            if distance_to_next_location < self.closest_distance_to_next_location:
                self.closest_distance_to_next_location = distance_to_next_location
                self.time_of_closest_distance = self.bot.time
            if distance_to_next_location < 2 or \
                    self.closest_distance_to_next_location < 30 and self.bot.time - self.time_of_closest_distance > 5:
                self.next_location.last_seen = self.bot.time
                self.next_location = None
                self.closest_distance_to_next_location = float('inf')
