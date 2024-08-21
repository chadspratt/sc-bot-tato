from __future__ import annotations
import enum
from typing import Set, Union, List

from loguru import logger
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from sc2.constants import UnitTypeId

from ..mixins import GeometryMixin
from .formation import FormationType, ParentFormation
from ..micro.base_unit_micro import BaseUnitMicro
from ..micro.micro_factory import MicroFactory
from .base_squad import BaseSquad
from ..enemy import Enemy


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
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.enemy = enemy
        self.orders = []
        self.current_order = SquadOrderEnum.IDLE
        self._destination: Point2 = None
        self.previous_position: Point2 = None
        self.targets: Units = Units([], bot_object=self.bot)
        self.parent_formation: ParentFormation = ParentFormation(self.bot)
        self.units_in_formation_position: Set[int] = set()
        self.destination_facing: float = None

    def execute(self, squad_order: SquadOrder):
        self.orders.append(squad_order)

    def __repr__(self):
        return f"FormationSquad({self.name},{self.state},{len(self.units)}, {self.parent_formation})"

    def draw_debug_box(self):
        if self.parent_formation.front_center:
            self.bot.client.debug_sphere_out(self.convert_point2_to_3(self.parent_formation.front_center), 1.5, (0, 255, 255))
        super().draw_debug_box()

    @property
    def position(self) -> Point2:
        return self.parent_formation.front_center

    def transfer(self, unit: Unit, to_squad: BaseSquad):
        super().transfer(unit, to_squad)

    def recruit(self, unit: Unit):
        super().recruit(unit)
        self.update_formation(reset=True)

    def get_report(self) -> str:
        has = len(self.units)
        return f"{self.name}({has})"

    def update_references(self):
        self.units = self.get_updated_unit_references(self.units)
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

    async def attack(self, targets: Union[Point2, Units]):
        if not targets or not self.units:
            return
        target_position = targets
        if isinstance(targets, Units):
            self.targets = Units(targets, self.bot)
            self.current_order = SquadOrderEnum.ATTACK

            closest_target = self.targets.closest_to(self.parent_formation.front_center)
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
        # check if squad is in formation
        self.update_units_in_formation_position(formation_positions)

        logger.debug(f"squad {self.name} moving from {self.position} to {self._destination} with {formation_positions.values()}")
        for unit in self.units:
            logger.debug(f"unit {unit} moving to {formation_positions[unit.tag]}")
            if unit.tag in self.bot.unit_tags_received_action:
                logger.debug(f"unit {unit} already received an order {unit.orders}")
                continue
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit, self.bot)
            logger.debug(f"unit {unit} using micro {micro}")
            await micro.move(unit, formation_positions[unit.tag], self.enemy)
        # TODO add leader movement vector to positions so they aren't playing catch up

    def update_units_in_formation_position(self, formation_positions: dict[int, Point2]):
        self.units_in_formation_position.clear()
        for unit in self.units:
            if unit.distance_to(formation_positions[unit.tag]) < 3:
                self.units_in_formation_position.add(unit.tag)

    @property
    def formation_completion(self) -> float:
        return len(self.units_in_formation_position) / len(self.units)

    def get_regroup_destination(self) -> Point2:
        self.current_order = SquadOrderEnum.REGROUP
        # find a midpoint
        max_x = max_y = min_x = min_y = None
        for unit in self.units:
            unit.facing
            if max_x is None or unit.position.x > max_x:
                max_x = unit.position.x
            if max_y is None or unit.position.y > max_y:
                max_y = unit.position.y
            if min_x is None or unit.position.x < min_x:
                min_x = unit.position.x
            if min_y is None or unit.position.y < min_y:
                min_y = unit.position.y

        return Point2(((min_x + max_x) / 2, (min_y + max_y) / 2))
