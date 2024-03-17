from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit


class Squad:
    def __init__(
        self,
        bot: BotAI,
        composition: dict[UnitTypeId, int] = None,
        color: tuple[int] = (0, 255, 0),
        name: str = "fuckwits",
    ):
        self.bot = bot
        self.name = name
        self.composition = composition or {}
        self.color = color
        self._units: list[Unit] = []

    def wants(self, unit: Unit) -> int:
        _wants = self.composition.get(unit.type_id, 0)
        logger.info(f"{self.name} squad wants {_wants} {unit.type_id.name}")
        return _wants

    def has(self, unit: Unit) -> int:
        _has = sum([1 for u in self._units if u.type_id is unit.type_id])
        logger.info(f"{self.name} squad has {_has} {unit.type_id.name}")
        return _has

    def needs(self, unit: Unit) -> bool:
        return self.has(unit) < self.wants(unit)

    def refresh_unit_references(self):
        _units = []
        for unit in self.units:
            try:
                _units.append(self.bot.all_units.by_tag(unit.tag))
            except KeyError:
                logger.info(f"Couldn't find unit {unit}!")
        self._units = _units

    def draw_debug_box(self):
        for unit in self._units:
            self.bot.client.debug_box2_out(unit, color=self.color)

    def recruit(self, unit: Unit):
        logger.info(f"Recruiting {unit} into {self.name} squad")
        self._units.append(unit)

    @property
    def units(self):
        return list(self._units)

    def remove(self, unit: Unit):
        logger.info(f"Removing {unit} from {self.name} squad")
        try:
            self._units.remove(unit)
        except ValueError:
            logger.info("Unit not found in squad")

    def transfer(self, unit: Unit, to_squad: Squad):
        self.remove(unit)
        to_squad.recruit(unit)
