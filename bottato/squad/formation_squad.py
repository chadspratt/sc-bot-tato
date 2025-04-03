from __future__ import annotations
import enum
from typing import Union, List
# import traceback

from loguru import logger
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2, Point3
from sc2.constants import UnitTypeId

from ..mixins import GeometryMixin
from .formation import FormationType, ParentFormation
from ..micro.base_unit_micro import BaseUnitMicro
from ..micro.micro_factory import MicroFactory
from .base_squad import BaseSquad
from ..enemy import Enemy
from ..map.map import Map


class SquadOrderEnum(enum.Enum):
    IDLE = 0
    MOVE = 1
    ATTACK = 2
    DEFEND = 3
    RETREAT = 4
    REGROUP = 5


class SquadOrder:
    def __init__(
        self,
        order: SquadOrderEnum,
        targets: List[Unit],
        priority: int = 0,
    ):
        self.order = order
        self.targets = targets
        self.priority = priority


class FormationSquad(BaseSquad, GeometryMixin):
    def __init__(
        self,
        enemy: Enemy,
        map: Map,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.enemy = enemy
        self.map = map
        self.orders = []
        self.current_order = SquadOrderEnum.IDLE
        self._destination: Point2 = None
        self.previous_position: Point2 = None
        self.targets: Units = Units([], bot_object=self.bot)
        self.parent_formation: ParentFormation = ParentFormation(self.bot, self.map)
        self.destination_facing: float = None

    def execute(self, squad_order: SquadOrder):
        self.orders.append(squad_order)

    def __repr__(self):
        return f"FormationSquad({self.name},{self.state},{len(self.units)}, {self.parent_formation})"

    def draw_debug_box(self):
        if self.parent_formation.front_center:
            self.bot.client.debug_sphere_out(self.convert_point2_to_3(self.parent_formation.front_center), 1.5, (0, 255, 255))
            self.bot.client.debug_sphere_out(self.convert_point2_to_3(self.parent_formation.destination), 1.5, (255, 0, 255))

            previous_point3: Point3 = self.convert_point2_to_3(self.parent_formation.front_center)
            if self.parent_formation.path:
                for point in self.parent_formation.path:
                    next_point3: Point3 = self.convert_point2_to_3(point)
                    self.bot.client.debug_line_out(previous_point3, next_point3, (255, 50, 50))
                    self.bot.client.debug_sphere_out(next_point3, 0.5, (255, 50, 50))
                    previous_point3 = next_point3
            destination3: Point3 = self.convert_point2_to_3(self._destination)
            self.bot.client.debug_line_out(previous_point3, destination3, (255, 50, 50))

        super().draw_debug_box()

    @property
    def position(self) -> Point2:
        return self.parent_formation.front_center

    def transfer(self, unit: Unit, to_squad: BaseSquad):
        super().transfer(unit, to_squad)
        self.update_formation(reset=True)

    def transfer_all(self, to_squad: BaseSquad):
        super().transfer_all(to_squad)
        self.update_formation(reset=True)

    def recruit(self, unit: Unit):
        super().recruit(unit)
        self.update_formation(reset=True)

    def get_report(self) -> str:
        has = len(self.units)
        return f"{self.name}({has})"

    def update_references(self):
        super().update_references()
        self.targets = self.get_updated_unit_references(self.targets)

    def update_formation(self, reset=False):
        # decide formation(s)
        if reset:
            self.parent_formation.clear()
        if not self.parent_formation.formations:
            unit_type_order = [UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.HELLION, UnitTypeId.REAPER, UnitTypeId.BANSHEE, UnitTypeId.CYCLONE, UnitTypeId.VIKINGFIGHTER, UnitTypeId.BATTLECRUISER, UnitTypeId.THOR, UnitTypeId.RAVEN, UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED, UnitTypeId.MEDIVAC]
            y_offset = 0
            for unit_type in unit_type_order:
                if self.add_unit_formation(unit_type, y_offset):
                    y_offset -= 1

        logger.debug(f"squad {self.name} formation: {self.parent_formation}")

    def add_unit_formation(self, unit_type: UnitTypeId, y_offset: int) -> bool:
        units: Units = self.units.of_type(unit_type)
        if units:
            self.parent_formation.add_formation(FormationType.COLUMNS, units.tags, Point2((0, y_offset)))
            return True
        return False

    async def attack(self, targets: Union[Point2, Units, Unit]):
        if not targets or not self.units:
            return
        target_position = targets
        self.current_order = SquadOrderEnum.ATTACK
        if isinstance(targets, Unit):
            self.targets = Units([targets], self.bot)
            target_position = targets.position
        elif isinstance(targets, Units):
            self.targets = Units(targets, self.bot)
            reference_point = self.parent_formation.front_center or self.units.center
            closest_target = self.targets.closest_to(reference_point)
            target_position = closest_target.position
            logger.info(
                f"{self.name} Squad attacking {closest_target};"
            )
        else:
            logger.info(
                f"{self.name} Squad attacking {target_position};"
            )

        facing = self.get_facing(self.units.center, target_position)
        await self.move(target_position, facing)

    async def move(self, destination: Point2, destination_facing: float):
        self.current_order = SquadOrderEnum.MOVE
        self._destination = destination
        self.destination_facing = destination_facing

        formation_positions = self.parent_formation.get_unit_destinations(self._destination, self.units, destination_facing)

        logger.debug(f"squad {self.name} moving from {self.position} to {self._destination} with {formation_positions.values()}")
        # traceback.print_stack(limit=5)
        for unit in self.units:
            logger.debug(f"unit {unit} moving to {formation_positions[unit.tag]}")
            if unit.tag in self.bot.unit_tags_received_action:
                logger.debug(f"unit {unit} already received an order {unit.orders}")
                continue
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit, self.bot)
            logger.debug(f"unit {unit} using micro {micro}")
            await micro.move(unit, formation_positions[unit.tag], self.enemy)
