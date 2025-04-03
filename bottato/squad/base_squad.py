from __future__ import annotations
import enum

from loguru import logger
from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from ..mixins import UnitReferenceMixin
from .squad_type import SquadType, SquadTypeDefinitions


class SquadState(enum.Enum):
    FILLING = 0
    FULL = 1
    REDUCED = 3
    CRIPPLED = 4
    RESUPPLYING = 5
    DESTROYED = 6


class BaseSquad(UnitReferenceMixin):
    def __init__(
        self,
        *,
        type: SquadType = SquadTypeDefinitions['none'],
        bot: BotAI,
        color: tuple[int] = (0, 255, 0),
        name: str = None,
    ):
        self.bot = bot
        self.color = color
        self.name = name
        self.units: Units = Units([], bot_object=bot)
        self.state: SquadState = SquadState.FILLING
        self.staging_location: Point2 = None

    def draw_debug_box(self):
        # for unit in self.units:
        #     self.bot.client.debug_box2_out(
        #         unit, half_vertex_length=unit.radius, color=self.color
        #     )
        return

    @property
    def is_full(self) -> bool:
        return self.state == SquadState.FULL

    def __repr__(self) -> str:
        return f"BaseSquad({self.name},{self.state},{len(self.units)})"

    @property
    def is_empty(self) -> bool:
        return len(self.units) == 0

    def remove(self, unit: Unit):
        logger.info(f"Removing {unit} from {self.name} squad")
        try:
            self.units.remove(unit)
            if self.name == "unassigned":
                pass
            if not self.units:
                self.state = SquadState.DESTROYED
            elif self.state == SquadState.FULL:
                self.state = SquadState.REDUCED
            elif self.state == SquadState.REDUCED:
                has = len(self.units)
                if has < 5:
                    self.state = SquadState.CRIPPLED
        except ValueError:
            logger.info("Unit not found in squad")

    def remove_by_tag(self, unit_tag: int):
        for unit in self.units:
            if unit.tag == unit_tag:
                self.remove(unit)
                break

    def recruit(self, unit: Unit):
        logger.debug(f"Recruiting {unit} into {self.name} squad")
        self.units.append(unit)
        has = len(self.units)
        if has >= 10:
            self.state = SquadState.FULL

    def transfer(self, unit: Unit, to_squad: BaseSquad):
        self.remove(unit)
        to_squad.recruit(unit)

    def transfer_all(self, to_squad: BaseSquad):
        for unit in self.units:
            self.transfer(unit, to_squad)

    def transfer_by_type(self, unit_type: UnitTypeId, to_squad: BaseSquad) -> bool:
        for unit in self.units:
            if unit.type_id == unit_type:
                self.transfer(unit, to_squad)
                return True
        return False

    def unit_count(self, unit: Unit) -> int:
        _has = sum([1 for u in self.units if u.type_id is unit.type_id])
        logger.debug(f"{self.name} squad has {_has} {unit.type_id.name}")
        return _has
