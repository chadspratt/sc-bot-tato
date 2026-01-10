from __future__ import annotations
from typing import Dict, List

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units

from bottato.enemy import Enemy
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import GeometryMixin, timed_async
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.scouting_location import ScoutingLocation
from bottato.squad.squad import Squad


class HuntingSquad(Squad, GeometryMixin):
    def __init__(
        self,
        bot: BotAI,
        enemy: Enemy,
        intel: EnemyIntel,
        name: str,
        color: tuple[int, int, int]
    ):
        super().__init__(bot, name, color)
        self.enemy = enemy
        self.intel = intel
        self.units: Units = Units([], bot_object=bot)

        self.next_location: ScoutingLocation | None = None
        self.closest_distance_to_next_location = float('inf')
        self.time_of_closest_distance = 0

    def __repr__(self):
        return f"HuntingSquad({self.name},{len(self.units)})"

    unsafe_targets: Dict[int, float] = {}
    @timed_async
    async def hunt(self, target_types: List[UnitTypeId]):
        if not self.units:
            return

        targets = self.enemy.get_enemies().filter(lambda u: u.type_id in target_types)
        safe_targets = targets.filter(lambda u: u.tag not in self.unsafe_targets or self.bot.time - self.unsafe_targets[u.tag] > 20)
        if not safe_targets:     
            safe_targets = targets.filter(lambda u: u.tag not in self.unsafe_targets or self.bot.time - self.unsafe_targets[u.tag] > 5)
        safe_targets_near_base = safe_targets.filter(lambda u: self.closest_distance_squared(u, self.bot.structures) < 1600)
        candidates = safe_targets_near_base if safe_targets_near_base else safe_targets

        for unit in self.units:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
            if candidates:
                self.next_location = None
                self.closest_distance_to_next_location = float('inf')
                target = self.closest_unit_to_unit(unit, candidates)
                is_huntable = await micro.move(unit, target.position)
                if not is_huntable:
                    self.unsafe_targets[target.tag] = self.bot.time
            else:
                self.next_location = sorted(self.intel.scouting_locations, key=lambda loc: loc.last_seen)[0]
                distance_to_next_location = unit.distance_to_squared(self.next_location.position)
                if distance_to_next_location < self.closest_distance_to_next_location:
                    self.closest_distance_to_next_location = distance_to_next_location
                    self.time_of_closest_distance = self.bot.time
                # mark location as seen if can't get closer for 5 seconds
                if distance_to_next_location < 10 or \
                        self.closest_distance_to_next_location < 30 and self.bot.time - self.time_of_closest_distance > 5:
                    self.next_location.last_seen = self.bot.time
                    self.next_location = None
                    self.closest_distance_to_next_location = float('inf')
                else:
                    await micro.move(unit, self.next_location.position)
