from __future__ import annotations

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId

from ..mixins import UnitReferenceMixin
from .composition import Composition
from .squad_type import SquadType, SquadTypeDefinitions


class BaseSquad(UnitReferenceMixin):
    def __init__(
        self,
        *,
        type: SquadType = SquadTypeDefinitions['none'],
        bot: BotAI,
        color: tuple[int] = (0, 255, 0),
    ):
        self.bot = bot
        self.color = color
        self.units: Units = Units([], bot_object=bot)
        self.type = type
        self.composition: Composition = type.composition

    def draw_debug_box(self):
        for unit in self.units:
            self.bot.client.debug_box2_out(
                unit, half_vertex_length=unit.radius, color=self.color
            )
            # self.bot.client.debug_text_world(f"{unit.position}", self.convert_point2_to_3(unit.position))

    @property
    def is_full(self) -> bool:
        has = len(self.units)
        wants = sum([v for v in self.composition.current_units])
        return has >= wants

    @property
    def is_empty(self) -> bool:
        return len(self.units) == 0

    def remove(self, unit: Unit):
        logger.info(f"Removing {unit} from {self.name} squad")
        try:
            self.units.remove(unit)
        except ValueError:
            logger.info("Unit not found in squad")

    def remove_by_tag(self, unit_tag: int):
        for unit in self.units:
            if unit.tag == unit_tag:
                self.remove(unit)
                break

    def transfer(self, unit: Unit, to_squad: BaseSquad):
        self.remove(unit)
        to_squad.recruit(unit)

    def desired_unit_count(self, unit: Unit) -> int:
        _wants = self.composition.count_type(unit.type_id)
        logger.info(f"{self.name} squad wants {_wants} {unit.type_id.name}")
        return _wants

    def unit_count(self, unit: Unit) -> int:
        _has = sum([1 for u in self.units if u.type_id is unit.type_id])
        logger.info(f"{self.name} squad has {_has} {unit.type_id.name}")
        return _has

    def needs(self, unit: Unit = None) -> bool:
        if unit:
            return self.unit_count(unit) < self.desired_unit_count(unit)
        else:
            return self.unit_count()

    def needed_unit_types(self) -> list[UnitTypeId]:
        needed_types: list[UnitTypeId] = []
        counted_unit_tags: list[int] = []
        for unit_type in self.composition.current_units:
            for unit in self.units:
                if unit.tag in counted_unit_tags:
                    continue
                if unit.type_id == unit_type:
                    counted_unit_tags.append(unit.tag)
                    break
            else:
                needed_types.append(unit_type)
        return needed_types
