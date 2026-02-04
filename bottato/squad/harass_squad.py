from __future__ import annotations

import random
from typing import Dict

from cython_extensions.geometry import cy_distance_to, cy_towards
from sc2.bot_ai import BotAI
from sc2.data import race_townhalls
from sc2.position import Point2, Point3

from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import GeometryMixin, timed
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.squad import Squad
from bottato.unit_types import UnitTypes


class HarassSquad(Squad, GeometryMixin):
    def __init__(self, bot: BotAI, name: str):
        super().__init__(bot, name, color=(0, 255, 255))
        self.harass_locations: Dict[int, Point2] = {}
        self.arrived: Dict[int, bool] = {}
    def __repr__(self):
        return f"HarassSquad({self.name},{len(self.units)})"

    @timed
    def draw_debug_box(self):
        for harass_location in self.harass_locations.values():
            destination3: Point3 = self.convert_point2_to_3(harass_location, self.bot)
            self.bot.client.debug_sphere_out(destination3, 0.5, self.color)

    async def harass(self, intel: EnemyIntel):
        if not self.units:
            return

        for unit in self.units:
            if unit.tag not in self.harass_locations:
                self.harass_locations[unit.tag] = self.bot.enemy_start_locations[0]
                self.arrived[unit.tag] = False
            else:
                enemy_townhalls = self.bot.enemy_structures(race_townhalls[self.bot.enemy_race]).filter(lambda u: u.is_ready)
                if enemy_townhalls and enemy_townhalls.closest_distance_to(self.harass_locations[unit.tag]) > 10:
                    # enemy base destroyed, pick new
                    self.harass_locations[unit.tag] = enemy_townhalls.random.position
                    self.arrived[unit.tag] = False
                else:
                    distance_to_harass_location = self.units.closest_distance_to(self.harass_locations[unit.tag])
                    if not self.arrived[unit.tag]:
                        self.arrived[unit.tag] = distance_to_harass_location < 15
                    elif distance_to_harass_location > 15:
                        # arrived but got chased away, pick new location
                        self.arrived[unit.tag] = False
                        other_enemy_bases = [loc for loc in intel.enemy_base_built_times.keys() if loc.manhattan_distance(self.harass_locations[unit.tag]) > 15]
                        self.harass_locations[unit.tag] = random.choice(other_enemy_bases) if other_enemy_bases else self.harass_locations[unit.tag]

            micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
            nearby_enemies = self.bot.enemy_units.filter(lambda u: UnitTypes.can_attack_target(u, unit) and u.distance_to_squared(unit) < 225)
            threatening_structures = self.bot.enemy_structures.filter(
                lambda structure: structure.is_ready and UnitTypes.can_attack_target(structure, unit)
                    and cy_distance_to(structure.position, unit.position) < UnitTypes.range_vs_target(structure, unit) + 3)

            if not nearby_enemies and not threatening_structures:
                await micro.harass(unit, self.harass_locations[unit.tag])
                continue

            nearest_threat = None
            nearest_distance = 99999
            for threat in nearby_enemies + threatening_structures:
                distance = UnitTypes.get_range_buffer_vs_target(threat, unit)
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_threat = threat

            if not nearest_threat:
                await micro.harass(unit, self.harass_locations[unit.tag])
            else:
                enemy_range = UnitTypes.range_vs_target(nearest_threat, unit)
                if UnitTypes.range_vs_target(unit, nearest_threat) > enemy_range:
                    # kite enemies that we outrange
                    move_position = nearest_threat.position
                    if unit.weapon_cooldown != 0:
                        move_position = Point2(cy_towards(nearest_threat.position, unit.position, enemy_range + 1))
                    self.bot.client.debug_line_out(nearest_threat, self.convert_point2_to_3(move_position, self.bot), (255, 0, 0))
                    self.bot.client.debug_sphere_out(self.convert_point2_to_3(move_position, self.bot), 0.2, (255, 0, 0))
                    await micro.harass(unit, move_position)
                    continue
                else:
                    destination = self.harass_locations[unit.tag] if unit.health_percentage > 0.65 else self.bot.start_location
                    # try to circle around threats that outrange us
                    if unit.position == nearest_threat.position:
                        # avoid divide by zero
                        await micro.harass(unit, destination)
                    else:
                        circle_around_position = micro.get_circle_around_position(unit, nearest_threat.position, destination)
                        await micro.harass(unit, circle_around_position)
