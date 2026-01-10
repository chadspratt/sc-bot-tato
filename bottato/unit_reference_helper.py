from loguru import logger
from typing import Dict, List

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units


class UnitReferenceHelper:
    bot: BotAI
    units_by_tag: Dict[int, Unit]
    last_update_time: float = 0

    class UnitNotFound(Exception):
        pass

    @staticmethod
    def init(bot: BotAI, units_by_tag: Dict[int, Unit]):
        UnitReferenceHelper.bot = bot
        UnitReferenceHelper.units_by_tag = units_by_tag

    @staticmethod
    def update():
        UnitReferenceHelper.units_by_tag.clear()
        for unit in UnitReferenceHelper.bot.all_units:
            UnitReferenceHelper.units_by_tag[unit.tag] = unit
            UnitReferenceHelper.last_update_time = UnitReferenceHelper.bot.time

    @staticmethod
    def get_updated_unit_reference(unit: Unit | None) -> Unit:
        if unit is None:
            raise UnitReferenceHelper.UnitNotFound(
                "unit is None"
            )
        return UnitReferenceHelper.get_updated_unit_reference_by_tag(unit.tag)

    @staticmethod
    def get_updated_unit_reference_by_tag(tag: int) -> Unit:
        try:
            if UnitReferenceHelper.last_update_time != UnitReferenceHelper.bot.time:
                # for calls that happen between steps
                return UnitReferenceHelper.bot.all_units.by_tag(tag)
            return UnitReferenceHelper.units_by_tag[tag]
        except KeyError:
            raise UnitReferenceHelper.UnitNotFound(
                f"Cannot find unit with tag {tag}; maybe they died"
            )

    @staticmethod
    def get_updated_unit_references(units: Units) -> Units:
        _units = Units([], bot_object=UnitReferenceHelper.bot)
        for unit in units:
            try:
                _units.append(UnitReferenceHelper.get_updated_unit_reference(unit))
            except UnitReferenceHelper.UnitNotFound:
                logger.debug(f"Couldn't find unit {unit}!")
        return _units

    @staticmethod
    def get_updated_unit_references_by_tags(tags: List[int]) -> Units:
        _units = Units([], bot_object=UnitReferenceHelper.bot)
        for tag in tags:
            try:
                _units.append(UnitReferenceHelper.get_updated_unit_reference_by_tag(tag))
            except UnitReferenceHelper.UnitNotFound:
                logger.debug(f"Couldn't find unit {tag}!")
        return _units
