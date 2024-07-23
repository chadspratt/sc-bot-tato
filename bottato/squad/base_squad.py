from __future__ import annotations
import enum
from typing import List

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from ..mixins import UnitReferenceMixin
from .composition import Composition
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
        self.type = type
        self.bot = bot
        self.color = color
        self.name = name
        self.units: Units = Units([], bot_object=bot)
        self.composition: Composition = type.composition
        self.state: SquadState = SquadState.FILLING
        self.staging_location: Point2 = None

    def draw_debug_box(self):
        for unit in self.units:
            self.bot.client.debug_box2_out(
                unit, half_vertex_length=unit.radius, color=self.color
            )

    @property
    def is_full(self) -> bool:
        return self.state == SquadState.FULL

    def __repr__(self) -> str:
        return f"BaseSquad({self.name},{self.state},{len(self.units)}/{len(self.composition.current_units)})"

    @property
    def is_empty(self) -> bool:
        return len(self.units) == 0

    @property
    def can_expand(self) -> bool:
        return self.type.composition.expansion_units and len(self.composition.current_units) < self.type.composition.max_size

    def remove(self, unit: Unit):
        logger.info(f"Removing {unit} from {self.name} squad")
        try:
            self.units.remove(unit)
            if self.name == "unassigned":
                pass
            if not self.units or not self.composition.current_units:
                self.state = SquadState.DESTROYED
            elif self.state == SquadState.FULL:
                self.state = SquadState.REDUCED
            elif self.state == SquadState.REDUCED:
                has = len(self.units)
                wants = len(self.composition.current_units)
                if has / wants < 0.5:
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
        wants = len(self.composition.current_units)
        if has >= wants:
            self.state = SquadState.FULL

    def transfer(self, unit: Unit, to_squad: BaseSquad):
        self.remove(unit)
        to_squad.recruit(unit)

    def desired_unit_count(self, unit: Unit) -> int:
        _wants = self.composition.count_type(unit.type_id)
        logger.debug(f"{self.name} squad wants {_wants} {unit.type_id.name}")
        return _wants

    def unit_count(self, unit: Unit) -> int:
        _has = sum([1 for u in self.units if u.type_id is unit.type_id])
        logger.debug(f"{self.name} squad has {_has} {unit.type_id.name}")
        return _has

    def needs(self, unit: Unit = None) -> bool:
        if unit:
            return self.unit_count(unit) < self.desired_unit_count(unit)
        else:
            return self.unit_count()

    def needed_unit_types(self) -> List[UnitTypeId]:
        needed_types: List[UnitTypeId] = []
        counted_unit_tags: List[int] = []
        logger.debug(f"target composition {self.composition.current_units}")
        logger.debug(f"current units {[u.type_id for u in self.units]}")
        for unit_type in self.composition.current_units:
            for unit in self.units:
                if unit.tag in counted_unit_tags:
                    continue
                if unit.type_id == unit_type:
                    logger.debug(f"match for {unit_type}")
                    counted_unit_tags.append(unit.tag)
                    break
            else:
                logger.debug(f"no match for {unit_type}")
                needed_types.append(unit_type)

        if not needed_types:
            needed_types = self.expand()
            if needed_types:
                self.state = SquadState.FILLING
        return needed_types

    def expand(self) -> List[UnitTypeId]:
        remaining_space = self.composition.max_size - len(self.composition.current_units)
        if remaining_space > 0 and self.composition.expansion_units:
            logger.info(f"expanding {self}, {remaining_space} spaces remaining, adding from expansion list {self.composition.expansion_units}")
            number_to_add = min(remaining_space, len(self.composition.expansion_units))
            needed_types = self.composition.expansion_units[:number_to_add]
            logger.info(f"adding {needed_types} to current composition")
            self.composition.current_units.extend(needed_types)
            return needed_types
        return []
