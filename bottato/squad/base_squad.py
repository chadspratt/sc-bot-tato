from __future__ import annotations

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from bottato.mixins import UnitReferenceMixin
from bottato.squad.squad_type import SquadType, SquadTypeDefinitions


class BaseSquad(UnitReferenceMixin):
    def __init__(
        self,
        *,
        type: SquadType = SquadTypeDefinitions['none'],
        bot: BotAI,
        color: tuple[int, int, int] = (0, 255, 0),
        name: str = "",
    ):
        self.bot = bot
        self.color = color
        self.name = name
        self.units: Units = Units([], bot_object=bot)
        self.staging_location: Point2 = self.bot.start_location
        self.units_by_tag: dict[int, Unit] | None = None

    def draw_debug_box(self):
        return

    def __repr__(self) -> str:
        return f"BaseSquad({self.name},{len(self.units)})"

    def update_references(self, units_by_tag: dict[int, Unit]):
        self.units_by_tag = units_by_tag
        self.units = self.get_updated_unit_references(self.units, self.bot, units_by_tag)

    @property
    def is_empty(self) -> bool:
        return len(self.units) == 0

    def remove(self, unit: Unit):
        logger.debug(f"Removing {unit} from {self.name} squad")
        try:
            self.units.remove(unit)
            if self.name == "unassigned":
                pass
        except ValueError:
            logger.debug("Unit not found in squad")

    def remove_by_tag(self, unit_tag: int):
        for unit in self.units:
            if unit.tag == unit_tag:
                self.remove(unit)
                break

    def recruit(self, new_unit: Unit):
        for unit in self.units:
            if unit.tag == new_unit.tag:
                return
        self.units.append(new_unit)

    def transfer(self, unit: Unit, to_squad: BaseSquad):
        self.remove(unit)
        to_squad.recruit(unit)

    def transfer_all(self, to_squad: BaseSquad):
        for unit in [u for u in self.units]:
            self.transfer(unit, to_squad)

    # def transfer_by_type(self, unit_type: UnitTypeId, to_squad: BaseSquad) -> bool:
    #     for unit in self.units:
    #         if unit.type_id == unit_type:
    #             self.transfer(unit, to_squad)
    #             return True
    #     return False

    def unit_count(self, unit: Unit) -> int:
        _has = sum([1 for u in self.units if u.type_id is unit.type_id])
        logger.debug(f"{self.name} squad has {_has} {unit.type_id.name}")
        return _has
