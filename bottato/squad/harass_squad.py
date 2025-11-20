from __future__ import annotations
from typing import List
# import traceback

from sc2.position import Point2, Point3

from bottato.unit_types import UnitTypes
from bottato.mixins import GeometryMixin, TimerMixin
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.squad.base_squad import BaseSquad


class HarassSquad(BaseSquad, GeometryMixin, TimerMixin):
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
            nearby_enemies = self.bot.enemy_units.filter(lambda u: UnitTypes.can_attack_ground(u) and u.distance_to(unit) < 15)
            threatening_structures = self.bot.enemy_structures.filter(
                lambda structure: structure.is_ready and structure.can_attack_ground
                    and structure.distance_to(unit) < structure.ground_range + 3)

            if not nearby_enemies and not threatening_structures:
                await micro.move(unit, self.harass_location)
                continue

            nearest_threat = None
            nearest_distance = 99999
            for threat in nearby_enemies + threatening_structures:
                distance = threat.distance_to_squared(unit) - UnitTypes.ground_range(threat) ** 2
                if distance < nearest_distance:
                    nearest_distance = distance
                    nearest_threat = threat

            if not nearest_threat:
                await micro.move(unit, self.harass_location)
            elif UnitTypes.ground_range(nearest_threat) < UnitTypes.ground_range(unit):
                # kite enemies that we outrange
                # preDicted_position = self.preDict_future_unit_position(nearest_threat, 1, False)
                move_position = nearest_threat.position
                # if unit.weapon_cooldown != 0:
                #     move_position = nearest_threat.position.towards(unit, UnitTypes.ground_range(unit) - 0.5)
                self.bot.client.debug_line_out(nearest_threat, self.convert_point2_to_3(move_position, self.bot), (255, 0, 0))
                self.bot.client.debug_sphere_out(self.convert_point2_to_3(move_position, self.bot), 0.2, (255, 0, 0))
                await micro.move(unit, move_position)
                continue
            else:
            # elif nearest_threat.distance_to_squared(harass_location) < unit.distance_to_squared(harass_location):
                # try to circle around threats that outrange us
                circle_around_position = micro.get_circle_around_position(unit, nearest_threat.position, self.harass_location)
                await micro.move(unit, circle_around_position)
                continue
            
            # nearby_workers = nearby_enemies.filter(
            #     lambda enemy: enemy.type_id in (UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE))
            # if nearby_workers:
            #     nearby_workers.sort(key=lambda worker: worker.shield_health_percentage)
            #     most_injured: Unit = nearby_workers[0]
            #     move_position = most_injured.position
            #     if unit.weapon_cooldown != 0:
            #         move_position = most_injured.position.towards(unit, UnitTypes.ground_range(unit) - 0.5)
            #     await micro.move(unit, move_position)
            # else:
            #     await micro.move(unit, harass_location)
