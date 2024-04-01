from __future__ import annotations
import enum
import math

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from .mixins import UnitReferenceMixin
from .formation import FormationType, ParentFormation


class SquadOrderEnum(enum.Enum):
    IDLE = 0
    MOVE = 1
    ATTACK = 2
    DEFEND = 3
    RETREAT = 4


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


class BaseSquad(UnitReferenceMixin):
    def __init__(
        self,
        *,
        bot: BotAI,
        color: tuple[int] = (0, 255, 0),
    ):
        self.bot = bot
        self.color = color
        self._units: Units = Units([], bot_object=bot)

    @property
    def units(self):
        return self._units.copy()

    def draw_debug_box(self):
        for unit in self._units:
            self.bot.client.debug_box2_out(
                unit, half_vertex_length=unit.radius, color=self.color
            )

    def remove(self, unit: Unit):
        logger.info(f"Removing {unit} from {self.name} squad")
        try:
            self._units.remove(unit)
        except ValueError:
            logger.info("Unit not found in squad")

    def transfer(self, unit: Unit, to_squad: Squad):
        self.remove(unit)
        to_squad.recruit(unit)


class Squad(BaseSquad):
    def __init__(
        self,
        *,
        composition: dict[UnitTypeId, int] = None,
        name: str = "fuckwits",
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.orders = []
        self.name = name
        self.composition = composition or {}
        self.current_order = SquadOrderEnum.IDLE
        self.slowest_unit: Unit = None
        self._destination: Point2 = None
        self.previous_position: Point2 = None
        self.targets: Units = Units([], bot_object=self.bot)
        self.targets: Units = Units([], bot_object=self.bot)
        self.parent_formation: ParentFormation = ParentFormation(self.bot)

    def execute(self, squad_order: SquadOrder):
        self.orders.append(squad_order)

    def desired_unit_count(self, unit: Unit) -> int:
        _wants = self.composition.get(unit.type_id, 0)
        logger.info(f"{self.name} squad wants {_wants} {unit.type_id.name}")
        return _wants

    def unit_count(self, unit: Unit) -> int:
        _has = sum([1 for u in self._units if u.type_id is unit.type_id])
        logger.info(f"{self.name} squad has {_has} {unit.type_id.name}")
        return _has

    def needs(self, unit: Unit) -> bool:
        return self.unit_count(unit) < self.desired_unit_count(unit)

    @property
    def is_full(self) -> bool:
        has = len(self._units)
        wants = sum([v for v in self.composition.values()])
        return has >= wants

    @property
    def facing(self) -> float:
        angle = math.atan2(
            self._destination.y - self.previous_position.y, self._destination.x - self.previous_position.x
        )
        if angle < 0:
            angle += math.pi * 2
        return angle

    def recruit(self, unit: Unit):
        logger.info(f"Recruiting {unit} into {self.name} squad")
        if (
            self.slowest_unit is None
            or unit.movement_speed < self.slowest_unit.movement_speed
        ):
            self.slowest_unit = unit
        self._units.append(unit)
        self.update_formation(reset=True)

    def get_report(self) -> str:
        has = len(self._units)
        wants = sum([v for v in self.composition.values()])
        return f"{self.name}({has}/{wants})"

    def update_slowest_unit(self):
        slowest: Unit = None
        for unit in self.units:
            if slowest is None or unit.movement_speed < slowest.movement_speed:
                slowest = unit
        if self._destination is not None:
            slowest = self.units.of_type(slowest.type_id).furthest_to(self._destination)

        self.slowest_unit = slowest

    def update_references(self):
        self._units = self.get_updated_unit_references(self.units)
        self.targets = self.get_updated_unit_references(self.targets)
        self.update_slowest_unit()

    def update_formation(self, reset=False):
        # decide formation(s)
        if self.slowest_unit is None:
            return
        if reset:
            self.parent_formation.clear()
        if not self.parent_formation.formations:
            self.parent_formation.add_formation(FormationType.LINE, self._units.tags)
        if self.bot.enemy_units.closer_than(8.0, self.parent_formation.game_position):
            self.parent_formation.clear()
            self.parent_formation.add_formation(
                FormationType.HOLLOW_CIRCLE, self._units.tags
            )
        logger.info(f"squad {self.name} formation: {self.parent_formation}")

    def continue_order(self):
        if not self._units:
            return
        # calc front and position
        # move continuation
        if self.current_order == SquadOrderEnum.MOVE:
            self.continue_move()
        if self.current_order == SquadOrderEnum.ATTACK:
            self.continue_attack()

    def attack(self, targets: Units):
        if not targets:
            return

        self.targets = Units(targets, self.bot)
        self.current_order = SquadOrderEnum.ATTACK

        closest_target = self.targets.closest_to(self.slowest_unit)
        logger.info(
            f"{self.name} Squad attacking {closest_target};"
        )
        for unit in self.units:
            unit.attack(closest_target)

    def continue_attack(self):
        if self.targets:
            closest_target = self.targets.closest_to(self.slowest_unit)
            for unit in self.units:
                unit.attack(closest_target)

    def move(self, position: Point2):
        logger.info(
            f"{self.name} Squad moving to {position};"
        )
        self.current_order = SquadOrderEnum.MOVE
        self.previous_position = self.parent_formation.game_position
        self._destination = position

        self.continue_move()

    def continue_move(self):
        facing = None
        distance_moved = (self.parent_formation.game_position - self.previous_position).length
        if distance_moved < 5:
            facing = self.facing
        game_positions = self.parent_formation.get_unit_destinations(self._destination, self.slowest_unit, facing)
        logger.info(f"squad {self.name} moving from {self.parent_formation.game_position}/{self.slowest_unit.position} to {self._destination} with {game_positions.values()}")
        for unit in self.units:
            if unit.tag in self.bot.unit_tags_received_action:
                continue
            unit.attack(game_positions[unit.tag])

    def regroup(self):
        self.move(self.parent_formation.game_position)
