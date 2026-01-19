from __future__ import annotations
from loguru import logger
from typing import Dict, List, Tuple
# import traceback

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2, Point3
from sc2.unit import Unit
from sc2.units import Units

from bottato.building.build_step import BuildStep
from bottato.enemy import Enemy
from bottato.enums import SquadFormationType, UnitMicroType
from bottato.map.map import Map
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.squad.formation import ParentFormation
from bottato.squad.squad import Squad


class FormationSquad(Squad, GeometryMixin):
    def __init__(
        self,
        bot: BotAI,
        enemy: Enemy,
        map: Map,
        name: str,
        color: Tuple[int, int, int] = (0, 255, 0),
    ):
        super().__init__(bot, name, color)
        self.enemy = enemy
        self.map = map
        self.orders = []
        self._destination: Point2 | None = None
        self.previous_position: Point2 | None = None
        # self.targets: Units = Units([], bot_object=self.bot)
        self.parent_formation: ParentFormation = ParentFormation(self.bot, self.map)
        self.destination_facing: float | None = None
        self.last_ungrouped_time: float = -5
        self.executed_positions: Dict[int, Point2] = {}

    def __repr__(self):
        return f"FormationSquad({self.name},{len(self.units)}, {self.parent_formation})"

    @timed
    def draw_debug_box(self):
        if self.parent_formation.front_center:
            self.bot.client.debug_sphere_out(self.convert_point2_to_3(self.parent_formation.front_center, self.bot), 1.5, (0, 255, 255))
            if self.parent_formation.destination:
                self.bot.client.debug_sphere_out(self.convert_point2_to_3(self.parent_formation.destination, self.bot), 1.5, (255, 0, 255))

            previous_point3: Point3 = self.convert_point2_to_3(self.parent_formation.front_center, self.bot)
            if self.parent_formation.path:
                i = 0
                self.bot.client.debug_text_3d(f"{i};{previous_point3}", previous_point3, (255, 255, 255), size=9)
                for point in self.parent_formation.path:
                    i += 1
                    next_point3: Point3 = self.convert_point2_to_3(point, self.bot)
                    self.bot.client.debug_line_out(previous_point3, next_point3, (255, 50, 50))
                    self.bot.client.debug_sphere_out(next_point3, 0.7, (255, 50, 50))
                    self.bot.client.debug_text_3d(f"{i};{next_point3}", next_point3, (255, 255, 255), size=9)
                    previous_point3 = next_point3
            if self._destination:
                destination3: Point3 = self.convert_point2_to_3(self._destination, self.bot)
                self.bot.client.debug_line_out(previous_point3, destination3, (255, 50, 50))
                self.bot.client.debug_sphere_out(destination3, 0.5, (255, 50, 50))

    @property
    def position(self) -> Point2:
        if self.parent_formation.front_center:
            return self.parent_formation.front_center
        elif self.units:
            return self.units.center
        return self.bot.start_location

    def transfer(self, unit: Unit, to_squad: Squad):
        super().transfer(unit, to_squad)
        self.update_formation(reset=True)

    def transfer_all(self, to_squad: Squad):
        super().transfer_all(to_squad)
        self.update_formation(reset=True)

    def recruit(self, new_unit: Unit):
        super().recruit(new_unit)
        self.update_formation(reset=True)

    def get_report(self) -> str:
        has = len(self.units)
        return f"{self.name}({has})"

    @timed
    def update_formation(self, reset=False):
        # decide formation(s)
        if reset:
            self.parent_formation.clear()
        if not self.parent_formation.formations:
            ground_unit_type_order = [
                UnitTypeId.MARINE,
                UnitTypeId.VIKINGASSAULT,
                UnitTypeId.MARAUDER,
                UnitTypeId.WIDOWMINE,
                UnitTypeId.WIDOWMINEBURROWED,
                UnitTypeId.HELLION,
                UnitTypeId.REAPER,
                # UnitTypeId.BANSHEE,
                UnitTypeId.CYCLONE,
                # UnitTypeId.VIKINGFIGHTER,
                # UnitTypeId.BATTLECRUISER,
                UnitTypeId.THOR,
                UnitTypeId.GHOST,
                # UnitTypeId.RAVEN,
                # UnitTypeId.LIBERATOR,
                UnitTypeId.SIEGETANK,
                UnitTypeId.SIEGETANKSIEGED,
                # UnitTypeId.MEDIVAC
            ]
            flying_unit_type_order = [
                UnitTypeId.BANSHEE,
                UnitTypeId.VIKINGFIGHTER,
                UnitTypeId.BATTLECRUISER,
                UnitTypeId.RAVEN,
                UnitTypeId.LIBERATOR,
                UnitTypeId.MEDIVAC
            ]
            y_offset = 0
            for unit_type in ground_unit_type_order:
                if self.add_unit_formation(unit_type, y_offset):
                    y_offset -= 1
            for unit_type in flying_unit_type_order:
                if self.add_unit_formation(unit_type, y_offset):
                    y_offset -= 1

        logger.debug(f"squad {self.name} formation: {self.parent_formation}")

    def add_unit_formation(self, unit_type: UnitTypeId, y_offset: int) -> bool:
        units: Units = self.units.of_type(unit_type)
        if units:
            spacing = units[0].radius * 1.3
            self.parent_formation.add_formation(SquadFormationType.COLUMNS, units.tags, Point2((0, y_offset)), spacing=spacing)
            return True
        return False

    @timed_async
    async def move(self, destination: Point2, facing_position: Point2 | None = None, force_move: bool = False, blueprints: List[BuildStep] = []):
        if not self.units:
            return
        self._destination = destination
        most_grouped_unit, grouped_units = self.get_most_grouped_unit(self.units, self.bot, 10)
        if facing_position is None:
            if destination == self.position:
                facing_position = destination + (destination - most_grouped_unit.position)
            else:
                facing_position = destination + (destination - self.position)
        self.destination_facing = self.get_facing(destination, facing_position)

        # 1/3 of total command execution time
        formation_positions = self.parent_formation.get_unit_destinations(self._destination, self.units, grouped_units, self.destination_facing)

        logger.debug(f"squad {self.name} moving from {self.position} to {self._destination} with {formation_positions.values()}")
        for unit in self.units:
            if unit.tag in formation_positions:
                logger.debug(f"unit {unit} moving to {formation_positions[unit.tag]}")
                if unit.tag in self.bot.unit_tags_received_action:
                    logger.debug(f"unit {unit} already received an order {unit.orders}")
                    continue
                # don't block new construction
                for blueprint in blueprints:
                    position = blueprint.get_position()
                    if position:
                        if self.bot.distance_math_hypot_squared(position, formation_positions[unit.tag]) < 9:
                            formation_positions[unit.tag] = position.towards(formation_positions[unit.tag], 3)
                if formation_positions[unit.tag] is None:
                    logger.debug(f"unit {unit} has no formation position")
                    continue
                # don't spam duplicate move commands
                previous_position = self.executed_positions.get(unit.tag, None)
                micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
                logger.debug(f"unit {unit} using micro {micro}")
                # 1/3 of total command execution time
                if await micro.move(unit, formation_positions[unit.tag], force_move, previous_position=previous_position) == UnitMicroType.MOVE:
                    self.executed_positions[unit.tag] = formation_positions[unit.tag]
                elif unit.tag in self.executed_positions:
                    del self.executed_positions[unit.tag]

    @timed
    def is_grouped(self) -> bool:
        if self.bot.time - self.last_ungrouped_time < 2:
            # give it a couple seconds to regroup before checking again
            return False
        if self.units:
            most_grouped_unit, grouped_units = self.get_most_grouped_unit(self.units, self.bot, 10)
            if most_grouped_unit:
                distance_limit = 18 ** 2
                units_out_of_formation = self.units.filter(lambda u: u.age == 0 and u.tag not in grouped_units.tags and u.distance_to_squared(most_grouped_unit) > distance_limit)
                if len(units_out_of_formation) / len(self.units) < 0.4:
                    return True
                else:
                    self.last_ungrouped_time = self.bot.time
        return False
