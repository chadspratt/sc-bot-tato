from __future__ import annotations
from typing import List
# import traceback

from sc2.position import Point2, Point3

from bottato.unit_types import UnitTypes
from bottato.mixins import GeometryMixin, TimerMixin
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.squad.squad import Squad


class HarassSquad(Squad, GeometryMixin, TimerMixin):
    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.arrived = False
        self.harass_location: Point2 = self.bot.enemy_start_locations[0]
    def __repr__(self):
        return f"FormationSquad({self.name},{len(self.units)})"

    def draw_debug_box(self):
        if self.harass_location:
            destination3: Point3 = self.convert_point2_to_3(self.harass_location, self.bot)
            self.bot.client.debug_sphere_out(destination3, 0.5, (255, 50, 50))

    async def harass(self, newest_enemy_base: Point2 | None = None):
        if not self.units:
            return
        
        distance_to_harass_location = self.units.closest_distance_to(self.harass_location)
        if not self.arrived:
            self.arrived = distance_to_harass_location < 15
        elif distance_to_harass_location > 15:
            self.arrived = False
            if self.harass_location == self.bot.enemy_start_locations[0] and newest_enemy_base:
                self.harass_location = newest_enemy_base
            else:
                self.harass_location = self.bot.enemy_start_locations[0]

        for unit in self.units:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
            nearby_enemies = self.bot.enemy_units.filter(lambda u: UnitTypes.can_attack_target(u, unit) and u.distance_to(unit) < 15)
            threatening_structures = self.bot.enemy_structures.filter(
                lambda structure: structure.is_ready and UnitTypes.can_attack_target(structure, unit)
                    and structure.distance_to(unit) < UnitTypes.range_vs_target(structure, unit) + 3)

            if not nearby_enemies and not threatening_structures:
                await micro.harass(unit, self.harass_location)
                continue

            nearest_threat = None
            nearest_distance = 99999
            for threat in nearby_enemies + threatening_structures:
                distance = threat.distance_to_squared(unit) - UnitTypes.range_vs_target(threat, unit) ** 2
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_threat = threat

            if not nearest_threat:
                await micro.harass(unit, self.harass_location)
            else:
                enemy_range = UnitTypes.range_vs_target(nearest_threat, unit)
                if UnitTypes.range_vs_target(unit, unit) > enemy_range:
                    # kite enemies that we outrange
                    move_position = nearest_threat.position
                    if unit.weapon_cooldown != 0:
                        move_position = nearest_threat.position.towards(unit, enemy_range + 1)
                    self.bot.client.debug_line_out(nearest_threat, self.convert_point2_to_3(move_position, self.bot), (255, 0, 0)) # type: ignore
                    self.bot.client.debug_sphere_out(self.convert_point2_to_3(move_position, self.bot), 0.2, (255, 0, 0)) # type: ignore
                    await micro.harass(unit, move_position) # type: ignore
                    continue
                else:
                    destination = self.harass_location if unit.health_percentage > 0.65 else self.bot.start_location
                    # try to circle around threats that outrange us
                    if unit.position == nearest_threat.position:
                        # avoid divide by zero
                        await micro.harass(unit, destination)
                    else:
                        circle_around_position = micro.get_circle_around_position(unit, nearest_threat.position, destination)
                        await micro.harass(unit, circle_around_position)
