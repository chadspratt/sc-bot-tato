from __future__ import annotations
import enum
from typing import Set

from loguru import logger
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from ..mixins import GeometryMixin
from .formation import FormationType, ParentFormation
from .base_squad import BaseSquad


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
        targets: list[Unit],
        priority: int = 0,
    ):
        self.order = order
        self.targets = targets
        self.priority = priority


class FormationSquad(BaseSquad, GeometryMixin):
    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.orders = []
        self.current_order = SquadOrderEnum.IDLE
        self.leader: Unit = None
        self._destination: Point2 = None
        self.previous_position: Point2 = None
        self.targets: Units = Units([], bot_object=self.bot)
        self.parent_formation: ParentFormation = ParentFormation(self.bot)
        self.units_in_formation_position: Set[int] = set()
        self.destination_facing: float = None

    def execute(self, squad_order: SquadOrder):
        self.orders.append(squad_order)

    @property
    def position(self) -> Point2:
        return self.parent_formation.game_position

    def recruit(self, unit: Unit):
        super().recruit(unit)
        if self.leader is None:
            self.leader = unit
            self.units_in_formation_position.add(unit.tag)
        self.update_formation(reset=True)

    def get_report(self) -> str:
        has = len(self.units)
        wants = len(self.composition.current_units)
        return f"{self.name}({has}/{wants})"

    def update_leader(self):
        new_slowest: Unit = None

        candidates: Units = Units([
            unit for unit in self.units
            if unit.tag in self.units_in_formation_position
        ], self.bot)

        if not candidates:
            candidates = self.units

        leader_can_fly = True
        for unit in candidates:
            if not unit.is_flying:
                leader_can_fly = False
                break

        for unit in candidates:
            if not leader_can_fly and unit.is_flying:
                continue
            if new_slowest is None or unit.movement_speed < new_slowest.movement_speed:
                new_slowest = unit

        self.leader = new_slowest

    def update_references(self):
        self.units = self.get_updated_unit_references(self.units)
        self.targets = self.get_updated_unit_references(self.targets)
        self.update_leader()

    def update_formation(self, reset=False):
        # decide formation(s)
        if self.leader is None:
            return
        if reset:
            self.parent_formation.clear()
        if not self.parent_formation.formations:
            self.parent_formation.add_formation(FormationType.COLUMNS, self.units.tags)
        if self.bot.enemy_units.closer_than(8.0, self.position):
            self.parent_formation.clear()
            self.parent_formation.add_formation(
                FormationType.HOLLOW_CIRCLE, self.units.tags
            )
        logger.info(f"squad {self.name} formation: {self.parent_formation}")

    def attack(self, targets: Units):
        if not targets or not self.units:
            return

        self.targets = Units(targets, self.bot)
        self.current_order = SquadOrderEnum.ATTACK

        closest_target = self.targets.closest_to(self.leader)
        logger.info(
            f"{self.name} Squad attacking {closest_target};"
        )

        for unit in self.units:
            if unit.target_in_range(closest_target):
                unit.attack(closest_target)

        self.move(closest_target.position, 0.0)
        # self.move(closest_target.position, self.get_facing(self.position, closest_target.position))

    def move(self, destination: Point2, destination_facing: float):
        self.current_order = SquadOrderEnum.MOVE
        self._destination = destination
        self.destination_facing = destination_facing

        formation_positions = self.parent_formation.get_unit_destinations(self._destination, self.leader, destination_facing)
        # check if squad is in formation
        self.update_units_in_formation_position(formation_positions)
        if self.formation_completion < 0.4:
            # if not, regroup
            regroup_point = self.get_regroup_destination()
            logger.info(f"squad {self.name} regrouping at {regroup_point}")
            formation_positions = self.parent_formation.get_unit_destinations(regroup_point, self.leader, destination_facing)

        logger.info(f"squad {self.name} moving from {self.position}/{self.leader.position} to {self._destination} with {formation_positions.values()}")
        for unit in self.units:
            if unit.tag in self.bot.unit_tags_received_action:
                continue
            unit.attack(formation_positions[unit.tag])
        # TODO add leader movement vector to positions so they aren't playing catch up

    def update_units_in_formation_position(self, formation_positions: dict[int, Point2]):
        self.units_in_formation_position.clear()
        self.units_in_formation_position.add(self.leader.tag)
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
