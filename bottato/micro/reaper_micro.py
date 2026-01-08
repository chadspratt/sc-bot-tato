from __future__ import annotations
from typing import List
from loguru import logger

from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Pointlike
from sc2.protocol import ProtocolError
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

from bottato.unit_types import UnitTypes
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.micro.base_unit_micro import BaseUnitMicro


class ReaperMicro(BaseUnitMicro, GeometryMixin):
    grenade_cooldown = 14.0
    grenade_timer = 1.7
    attack_health = 0.65
    retreat_health = 0.8

    grenade_cooldowns: dict[int, float] = {}
    unconfirmed_grenade_throwers: List[int] = []

    excluded_types = [UnitTypeId.EGG, UnitTypeId.LARVA]
    @timed_async
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        targets: Units = self.enemy.get_enemies_in_range(unit, include_structures=False, excluded_types=self.excluded_types)
        grenade_targets: List[Point2] = []
        if targets and await self.grenade_available(unit):
            for target_unit in targets:
                if target_unit.is_flying or target_unit.age > 0:
                    continue
                future_target_position = self.enemy.get_predicted_position(target_unit, self.grenade_timer)
                future_target_distance = future_target_position.distance_to(unit.position)
                if future_target_distance > 5:
                    continue
                grenade_target: Point2 = future_target_position
                if target_unit.is_facing(unit, angle_error=0.15):
                    # throw towards current position to avoid cutting off own retreat when predicted position is behind
                    grenade_target = unit.position.towards(target_unit.position, future_target_distance)
                grenade_targets.append(grenade_target)

        if grenade_targets:
            # choose furthest to reduce chance of grenading self
            grenade_target = min(grenade_targets, key=lambda p: unit.position._distance_squared(p))
            logger.debug(f"{unit} grenading {grenade_target}")
            self.throw_grenade(unit, grenade_target)
            return True

        return False

    @timed
    def _harass_attack_something(self, unit, health_threshold, harass_location: Point2, force_move: bool = False):
        if unit.health_percentage < self.attack_health:
            return False

        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack

        # nearby_enemies: Units
        candidates = self.enemy.get_candidates(included_types=[UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE])
        worker_buffer = 0 if can_attack else 5
        nearby_workers = self.enemy.in_attack_range(unit, candidates, worker_buffer)
        if not nearby_workers and worker_buffer == 0:
            nearby_workers = self.enemy.in_attack_range(unit, candidates, 5)

        threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=5)
        threats = threats.filter(lambda enemy: enemy.type_id not in UnitTypes.NON_THREATS)

        target = None
        if nearby_workers:
            target = nearby_workers.sorted(key=lambda t: t.shield + t.health).first
        if threats:
            closest_distance: float = float('inf')
            for threat in threats:
                threat_range = UnitTypes.ground_range(threat)
                if threat_range > unit.ground_range:
                    # don't attack enemies that outrange
                    return False
                threat_distance = self.distance_squared(unit, threat) - threat_range
                if threat_distance < closest_distance:
                    closest_distance = threat_distance
                    target = threat

        if not target:
            if unit.tag in self.harass_location_reached_tags:
                nearest_worker, _ = self.enemy.get_closest_target(unit, included_types=UnitTypes.WORKER_TYPES)
                if nearest_worker:
                    if can_attack:
                        return self._kite(unit, nearest_worker)
                    else:
                        unit.move(nearest_worker.position)
                        return True
            return False

        if target.age > 0:
            height_difference = target.position3d.z - self.bot.get_terrain_z_height(unit)
            if height_difference > 0.5:
                # don't attack enemies significantly higher than us
                return False
        return self._kite(unit, target)

    @timed_async
    async def _harass_retreat(self, unit: Unit, health_threshold: float, harass_location: Point2) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        threats = self.enemy.threats_to_friendly_unit(unit, attack_range_buffer=6)

        do_retreat = False

        if not threats:
            if unit.health_percentage >= health_threshold:
                return False
            # just stop and wait for regen
            unit.stop()
            return True

        for threat in threats:
            if UnitTypes.ground_range(threat) > unit.ground_range:
                # just run away from threats
                do_retreat = True
                break

        # check if incoming damage will bring unit below health threshold
        if not do_retreat:
            if not unit.health_max:
                # rare weirdness
                return True
            hp_threshold = unit.health_max * health_threshold
            current_health = unit.health
            for threat in threats:
                current_health -= threat.calculate_damage_vs_target(unit)[0]
                if current_health < hp_threshold:
                    do_retreat = True
                    break

        if do_retreat:
            destination = harass_location
            # retreat_to_start =  unit.health_percentage < health_threshold or unit.distance_to_squared(harass_location) < 400
            retreat_to_start =  True
            if retreat_to_start:
                destination = self.bot.start_location
            avg_threat_position = threats.center
            if unit.distance_to(destination) < avg_threat_position.distance_to(destination) + 2:
                # if closer to start or already near enemy, move past them to go home
                unit.move(destination)
                return True
            if retreat_to_start:
                retreat_position = unit.position.towards(avg_threat_position, -5)
                if self.bot.in_pathing_grid(retreat_position):
                    unit.move(retreat_position)
                else:
                    if unit.position == avg_threat_position:
                        # avoid divide by zero
                        unit.move(destination)
                    else:
                        circle_around_position = self.get_circle_around_position(unit, avg_threat_position, destination)
                        unit.move(circle_around_position.towards(destination, 2))
                return True
            else:
                circle_around_position = self.get_circle_around_position(unit, avg_threat_position, destination)
                unit.move(circle_around_position)
                return True

        return False

    async def grenade_jump(self, unit: Unit, target: Unit) -> bool:
        if await self.grenade_available(unit):
            logger.debug(f"{unit} grenading {target}")
            self.throw_grenade(unit, self.predict_future_unit_position(target, self.grenade_timer - 1, self.bot))
            return True
        return False

    def throw_grenade(self, unit: Unit, target: Point2):
        unit(AbilityId.KD8CHARGE_KD8CHARGE, target)
        self.unconfirmed_grenade_throwers.append(unit.tag)

    async def grenade_available(self, unit: Unit) -> bool:
        if unit.tag in self.unconfirmed_grenade_throwers:
            try:
                available = await self.bot.can_cast(unit, AbilityId.KD8CHARGE_KD8CHARGE, only_check_energy_and_cooldown=True)
            except ProtocolError:
                # game ended
                return False
            self.unconfirmed_grenade_throwers.remove(unit.tag)
            if not available:
                self.grenade_cooldowns[unit.tag] = self.bot.time + self.grenade_cooldown
            else:
                return True
        elif unit.tag not in self.grenade_cooldowns:
            return True
        elif self.grenade_cooldowns[unit.tag] < self.bot.time:
            del self.grenade_cooldowns[unit.tag]
            return True
        return False
