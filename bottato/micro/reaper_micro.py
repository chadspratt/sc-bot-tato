from __future__ import annotations
from loguru import logger

from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.protocol import ProtocolError
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId

from bottato.unit_types import UnitTypes
from bottato.mixins import GeometryMixin
from bottato.micro.base_unit_micro import BaseUnitMicro


class ReaperMicro(BaseUnitMicro, GeometryMixin):
    grenade_cooldown = 14.0
    grenade_timer = 1.7
    attack_health = 0.65
    retreat_health = 0.8

    grenade_cooldowns: dict[int, int] = {}
    unconfirmed_grenade_throwers: list[int] = []

    excluded_types = [UnitTypeId.EGG, UnitTypeId.LARVA]
    async def _use_ability(self, unit: Unit, target: Point2, health_threshold: float, force_move: bool = False) -> bool:
        if unit.health_percentage < self.attack_health:
            # too much risk of grenading self
            return False
        targets: Units = self.enemy.get_enemies_in_range(unit, include_structures=False, excluded_types=self.excluded_types)
        grenade_targets: list[Point2] = []
        if targets and await self.grenade_available(unit):
            for target_unit in targets:
                if target_unit.is_flying:
                    continue
                future_target_position = self.enemy.get_predicted_position(target_unit, self.grenade_timer)
                # future_target_position = target_unit.position
                grenade_target = future_target_position
                # grenade_target = future_target_position.towards(unit).
                if unit.in_ability_cast_range(AbilityId.KD8CHARGE_KD8CHARGE, grenade_target):
                    logger.debug(f"{unit} grenade candidates {target_unit}: {future_target_position} -> {grenade_target}")
                    grenade_targets.append(grenade_target)

        if grenade_targets:
            # choose furthest to reduce chance of grenading self
            grenade_target = unit.position.furthest(grenade_targets)
            logger.debug(f"{unit} grenading {grenade_target}")
            self.throw_grenade(unit, grenade_target)
            return True

        return False

    def _attack_something(self, unit, health_threshold, force_move: bool = False):
        if unit.health_percentage < self.attack_health:
            threats = self.enemy.threats_to(unit)
            if threats:
                return False
        if unit.weapon_cooldown > self.time_in_frames_to_attack:
            return False

        nearby_enemies = self.enemy.get_enemies_in_range(unit, include_structures=False, include_destructables=False)
        if not nearby_enemies:
            return False

        # enemy_workers = nearby_enemies.filter(lambda enemy: enemy.type_id in (UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE))
        threats = nearby_enemies.filter(lambda enemy: enemy.type_id not in (UnitTypeId.MULE, UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE, UnitTypeId.LARVA, UnitTypeId.EGG))

        if threats:
            for threat in threats:
                if UnitTypes.ground_range(threat) > unit.ground_range:
                    # don't attack enemies that outrange
                    return False
        can_attack = unit.weapon_cooldown <= self.time_in_frames_to_attack
        if can_attack:
            weakest_enemy = nearby_enemies.sorted(key=lambda t: t.shield + t.health).first
            return self._kite(unit, weakest_enemy)
        return self._stay_at_max_range(unit, nearby_enemies)

    async def _retreat(self, unit: Unit, health_threshold: float) -> bool:
        if unit.tag in self.bot.unit_tags_received_action:
            return False
        threats = self.enemy.threats_to(unit, attack_range_buffer=4)

        if not threats:
            if unit.health_percentage >= health_threshold:
                return False
            # just stop and wait for regen
            unit.stop()
            return True

        # retreat if there is nothing this unit can attack
        do_retreat = False
        visible_threats = threats.filter(lambda t: t.age == 0)
        targets = UnitTypes.in_attack_range_of(unit, visible_threats, bonus_distance=3)
        if not targets:
            do_retreat = True

        # check if incoming damage will bring unit below health threshold
        if not do_retreat:
            total_potential_damage = sum([threat.calculate_damage_vs_target(unit)[0] for threat in threats])
            if not unit.health_max:
                # rare weirdness
                return True
            if (unit.health - total_potential_damage) / unit.health_max < health_threshold:
                do_retreat = True

        if do_retreat:
            avg_threat_position = threats.center
            if unit.distance_to(self.bot.start_location) < avg_threat_position.distance_to(self.bot.start_location) + 2:
                # if closer to start or already near enemy, move past them to go home
                unit.move(self.bot.start_location)
                return True
            retreat_position = unit.position.towards(avg_threat_position, -5)
            # .towards(self.bot.start_location, 2)
            if self.bot.in_pathing_grid(retreat_position):
                unit.move(retreat_position)
            else:
                if unit.position == avg_threat_position:
                    # avoid divide by zero
                    unit.move(self.bot.start_location)
                else:
                    threat_to_unit_vector = (unit.position - avg_threat_position).normalized
                    tangent_vector = Point2((-threat_to_unit_vector.y, threat_to_unit_vector.x)) * unit.movement_speed
                    away_from_enemy_position = unit.position.towards(avg_threat_position, -1)
                    circle_around_positions = [away_from_enemy_position + tangent_vector, away_from_enemy_position - tangent_vector]
                    path_to_start = self.map.get_path_points(unit.position, self.bot.start_location)
                    next_waypoint = self.bot.start_location
                    if len(path_to_start) > 1:
                        next_waypoint = path_to_start[1]
                    circle_around_positions.sort(key=lambda pos: pos.distance_to(next_waypoint))
                    unit.move(circle_around_positions[0].towards(self.bot.start_location, 2))
            return True
        return False

    async def grenade_jump(self, unit: Unit, target: Unit) -> bool:
        if await self.grenade_available(unit):
            logger.debug(f"{unit} grenading {target}")
            self.throw_grenade(unit, self.predict_future_unit_position(target, self.grenade_timer - 1))
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
