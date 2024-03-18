from loguru import logger
from sc2.unit import Unit
from sc2.units import Units


class UnitReferenceMixin:
    class UnitNotFound(Exception):
        pass

    def get_updated_unit_reference(self, unit: Unit) -> Unit:
        try:
            return self.bot.all_units.by_tag(unit.tag)
        except KeyError:
            raise self.UnitNotFound(
                f"Cannot find unit with tag {unit.tag}; maybe they died"
            )

    def get_updated_units_references(self, units: Units) -> Units:
        _units = Units([], bot_object=self.bot)
        for unit in units:
            try:
                _units.append(self.get_updated_unit_reference(unit))
            except self.UnitNotFound:
                logger.info(f"Couldn't find unit {unit}!")
        return _units
