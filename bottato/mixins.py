import math
from loguru import logger
from typing import List

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3


class UnitReferenceMixin:
    class UnitNotFound(Exception):
        pass

    def convert_point2_to_3(self, point2: Point2) -> Point3:
        height: float = self.bot.get_terrain_z_height(point2)
        return Point3((point2.x, point2.y, height))

    def get_updated_unit_reference(self, unit: Unit) -> Unit:
        if unit is None:
            raise self.UnitNotFound(
                "unit is None"
            )
        return self.get_updated_unit_reference_by_tag(unit.tag)

    def get_updated_unit_reference_by_tag(self, tag: int) -> Unit:
        try:
            return self.bot.all_units.by_tag(tag)
        except KeyError:
            raise self.UnitNotFound(
                f"Cannot find unit with tag {tag}; maybe they died"
            )

    def get_updated_unit_references(self, units: Units) -> Units:
        _units = Units([], bot_object=self.bot)
        for unit in units:
            try:
                _units.append(self.get_updated_unit_reference(unit))
            except self.UnitNotFound:
                logger.info(f"Couldn't find unit {unit}!")
        return _units

    def get_updated_unit_references_by_tags(self, tags: List[int]) -> Units:
        _units = Units([], bot_object=self.bot)
        for tag in tags:
            try:
                _units.append(self.get_updated_unit_reference_by_tag(tag))
            except self.UnitNotFound:
                logger.info(f"Couldn't find unit {tag}!")
        return _units


class VectorFacingMixin:
    def get_facing(self, start_position: Point2, end_position: Point2):
        angle = math.atan2(
            end_position.y - start_position.y, end_position.x - start_position.x
        )
        if angle < 0:
            angle += math.pi * 2
        return angle


class UnitMicroMixin:
    def retreat(self, unit: Unit):
        bot: BotAI = self.bot
        attack_range_buffer = 2
        if unit.is_flying:
            threats = [enemy_unit for enemy_unit in bot.all_enemy_units
                       if enemy_unit.can_attack_air
                       and enemy_unit.air_range + attack_range_buffer > unit.distance_to(enemy_unit)]
        else:
            threats = [enemy_unit for enemy_unit in bot.all_enemy_units
                       if enemy_unit.can_attack_ground
                       and enemy_unit.ground_range + attack_range_buffer > unit.distance_to(enemy_unit)]
        retreat_vector = Point2([0, 0])
        map_center_vector = bot.game_info.map_center - unit.position
        if threats:
            for threat in threats:
                retreat_vector += unit.position - threat.position
            retreat_vector = retreat_vector.normalized * 2 + (map_center_vector).normalized
        else:
            retreat_vector = map_center_vector
        logger.info(f"unit {unit} retreating from {threats} in direction {retreat_vector}")
        unit.move(unit.position + retreat_vector)

    def attack_something(self, unit: Unit):
        bot: BotAI = self.bot
        if unit.weapon_cooldown == 0:
            targets = bot.all_enemy_units.in_attack_range_of(unit)
            if targets:
                target = targets.sorted(key=lambda enemy_unit: enemy_unit.health).first
                unit.attack(target)
                logger.info(f"unit {unit} attacking enemy {target}")
                return target
        return None
