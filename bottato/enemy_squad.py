from __future__ import annotations
from typing import Dict

from loguru import logger
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from .mixins import UnitReferenceMixin


NEARBY_THRESHOLD = 5


class EnemySquad(UnitReferenceMixin):
    def __init__(
        self,
        bot: BotAI,
        color: tuple[int] = (0, 255, 0),
    ):
        self.bot = bot
        self.color = color
        self._units: Units = Units([], bot_object=bot)
        self.last_seen_time_by_unit_tag: Dict[int, int]
        self.last_known_position: Point2 = None

    def update_unit_references(self):
        self._units = self.get_updated_unit_references_by_tags(
            self.last_seen_time_by_unit_tag.keys()
        )

    def near(self, unit: Unit) -> bool:
        return len(self._units.closer_than(NEARBY_THRESHOLD, unit)) > 0

    def draw_debug_box(self):
        for unit in self._units:
            self.bot.client.debug_box2_out(
                unit, half_vertex_length=unit.radius, color=self.color
            )

    def recruit(self, unit: Unit):
        logger.info(f"adding {unit} into {self.name} squad")
        if (
            self.slowest_unit is None
            or unit.movement_speed < self.slowest_unit.movement_speed
        ):
            self.slowest_unit = unit
        self._units.append(unit)

    def get_report(self) -> str:
        composition = {}
        for unit in self._units:
            composition.setdefault(unit.type_id, []).append(unit)
        buffer = ""
        for unit_type_id, units in composition.items():
            buffer += f"{unit_type_id}: {len(units)}, "
        return buffer

    @property
    def units(self):
        return self._units.copy()

    def remove(self, unit: Unit):
        logger.info(f"Removing {unit} from {self.name} squad")
        try:
            self._units.remove(unit)
        except ValueError:
            logger.info("Unit not found in squad")

    def transfer(self, unit: Unit, to_squad: EnemySquad):
        self.remove(unit)
        to_squad.recruit(unit)
