from __future__ import annotations
import enum

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2
from .util import get_refresh_references


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


class Squad:
    def __init__(
        self,
        bot: BotAI,
        composition: dict[UnitTypeId, int] = None,
        color: tuple[int] = (0, 255, 0),
        name: str = "fuckwits",
    ):
        self.orders = []
        self.bot = bot
        self.name = name
        self.composition = composition or {}
        self.color = color
        self.current_order = SquadOrderEnum.IDLE
        self.slowest_unit: Unit = None
        self._units: Units = Units([], bot_object=bot)
        self._position: Point2 = None
        self._destination: Point2 = None
        self.targets: Units = Units([], bot_object=bot)

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

    def continue_movement(self):
        for unit in self.units:
            if unit != self.slowest_unit:
                unit.move(self.slowest_unit.position)
            else:
                logger.info(
                    f"{self.name} Squad leader {self.slowest_unit} moving to {self._destination}"
                )
                unit.move(self._destination)

    def continue_attack(self):
        if self.targets and self.slowest_unit is not None:
            closest_target = self.targets.closest_to(self.slowest_unit)
            for unit in self.units:
                unit.attack(closest_target)

    def refresh_slowest_unit(self):
        if self.slowest_unit is not None:
            try:
                self.slowest_unit = self.bot.all_units.by_tag(self.slowest_unit.tag)
            except KeyError:
                self.slowest_unit = self.find_slowest_unit()

    def find_slowest_unit(self):
        slowest: Unit = None
        for unit in self.units:
            if slowest is None or unit.movement_speed < slowest.movement_speed:
                slowest = unit
        return slowest

    def manage_paperwork(self):
        self._units = get_refresh_references(self.units, self.bot)
        self.refresh_slowest_unit()
        self.targets = get_refresh_references(self.targets, self.bot)
        # calc front and position
        # move continuation
        if self.current_order == SquadOrderEnum.MOVE:
            self.continue_movement()
        if self.current_order == SquadOrderEnum.ATTACK:
            self.continue_attack()

    def draw_debug_box(self):
        for unit in self._units:
            self.bot.client.debug_box2_out(
                unit, half_vertex_length=unit.radius, color=self.color
            )

    def recruit(self, unit: Unit):
        logger.info(f"Recruiting {unit} into {self.name} squad")
        if (
            self.slowest_unit is None
            or unit.movement_speed < self.slowest_unit.movement_speed
        ):
            self.slowest_unit = unit
        self._units.append(unit)

    def attack(self, targets: Units, is_priority: bool = False):
        if not targets:
            return
        if is_priority or self.current_order in (
            SquadOrderEnum.IDLE,
            SquadOrderEnum.MOVE,
        ):
            self.targets = Units(targets, self.bot)
            self.current_order = SquadOrderEnum.ATTACK

            closest_target = self.targets.closest_to(self.slowest_unit)
            logger.info(
                f"{self.name} Squad attacking {closest_target}; is_priority: {is_priority}"
            )
            for unit in self.units:
                unit.attack(closest_target)

    def move(self, position: Point2, is_priority: bool = False):
        if self.slowest_unit.distance_to(position) < 1:
            logger.info(f"{self.name} Squad arrived at {position}")
            return
        if self.current_order == SquadOrderEnum.IDLE or is_priority:
            logger.info(
                f"{self.name} Squad moving to {position}; is_priority: {is_priority}"
            )
            self.current_order = SquadOrderEnum.MOVE
            self._destination = position

            for unit in self.units:
                if unit == self.slowest_unit:
                    logger.info(
                        f"{self.name} Squad leader {self.slowest_unit} moving to {position}"
                    )
                    self.slowest_unit.move(position)
                    break

    def check_order_complete(self):
        min_distance = 5
        if self.current_order == SquadOrderEnum.ATTACK:
            for target in self.targets:
                if target.health > 0:
                    break
            else:
                self.current_order = SquadOrderEnum.IDLE
        elif self.current_order == SquadOrderEnum.MOVE:
            for unit in self.units:
                if unit.distance_to(self._destination) > min_distance:
                    break
            else:
                self.current_order = SquadOrderEnum.IDLE

    @property
    def is_full(self) -> bool:
        has = len(self._units)
        wants = sum([v for v in self.composition.values()])
        logger.info(f"{self.name} has {has} units, wants {wants}")
        return has >= wants

    @property
    def units(self):
        return self._units.copy()

    def remove(self, unit: Unit):
        logger.info(f"Removing {unit} from {self.name} squad")
        try:
            self._units.remove(unit)
        except ValueError:
            logger.info("Unit not found in squad")

    def transfer(self, unit: Unit, to_squad: Squad):
        self.remove(unit)
        to_squad.recruit(unit)
