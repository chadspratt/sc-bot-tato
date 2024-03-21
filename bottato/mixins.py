from loguru import logger
from typing import List

from sc2.unit import Unit
from sc2.units import Units


class UnitReferenceMixin:
    class UnitNotFound(Exception):
        pass

    def get_updated_unit_reference(self, unit: Unit) -> Unit:
        return self.get_updated_unit_reference_by_tag(unit.tag)

    def get_updated_unit_reference_by_tag(self, tag: int) -> Unit:
        try:
            return self.bot.all_units.by_tag(tag)
        except KeyError:
            raise self.UnitNotFound(
                f"Cannot find unit with tag {tag}; maybe they died"
            )

    def get_updated_units_references(self, units: Units) -> Units:
        _units = Units([], bot_object=self.bot)
        for unit in units:
            try:
                _units.append(self.get_updated_unit_reference(unit))
            except self.UnitNotFound:
                logger.info(f"Couldn't find unit {unit}!")
        return _units

    def get_updated_units_references_by_tags(self, tags: List[int]) -> Units:
        _units = Units([], bot_object=self.bot)
        for tag in tags:
            try:
                _units.append(self.get_updated_unit_reference_by_tag(tag))
            except self.UnitNotFound:
                logger.info(f"Couldn't find unit {tag}!")
        return _units
