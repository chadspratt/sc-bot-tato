from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS

from ..mixins import UnitReferenceMixin


class Facility():
    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.add_on_type = UnitTypeId.NOTAUNIT
        self.addon_destroyed_time = None
        self.in_progress_unit: Unit = None
        self.capacity = 1

    def set_add_on_type(self, add_on_type: UnitTypeId) -> None:
        self.add_on_type = add_on_type
        if add_on_type == UnitTypeId.REACTOR:
            self.capacity = 2


class Production(UnitReferenceMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.facilities = {
            UnitTypeId.BARRACKS: {
                UnitTypeId.TECHLAB: [],
                UnitTypeId.REACTOR: [],
                UnitTypeId.NOTAUNIT: []
            },
            UnitTypeId.FACTORY: {
                UnitTypeId.TECHLAB: [],
                UnitTypeId.REACTOR: [],
                UnitTypeId.NOTAUNIT: []
            },
            UnitTypeId.STARPORT: {
                UnitTypeId.TECHLAB: [],
                UnitTypeId.REACTOR: [],
                UnitTypeId.NOTAUNIT: []
            },
        }
        self.needs_tech_lab: list[UnitTypeId] = [
            UnitTypeId.RAVEN,
            UnitTypeId.BANSHEE,
            UnitTypeId.SIEGETANK,
            UnitTypeId.BATTLECRUISER
        ]
        self.add_on_types: list[UnitTypeId] = [
            UnitTypeId.BARRACKSTECHLAB,
            UnitTypeId.BARRACKSREACTOR,
            UnitTypeId.FACTORYTECHLAB,
            UnitTypeId.FACTORYREACTOR,
            UnitTypeId.STARPORTTECHLAB,
            UnitTypeId.STARPORTREACTOR
        ]
        self.add_on_type_lookup: dict[UnitTypeId, UnitTypeId] = {
            UnitTypeId.BARRACKS: {
                UnitTypeId.TECHLAB: UnitTypeId.BARRACKSTECHLAB,
                UnitTypeId.REACTOR: UnitTypeId.BARRACKSREACTOR,
            },
            UnitTypeId.FACTORY: {
                UnitTypeId.TECHLAB: UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.REACTOR: UnitTypeId.FACTORYREACTOR,
            },
            UnitTypeId.STARPORT: {
                UnitTypeId.TECHLAB: UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.REACTOR: UnitTypeId.STARPORTREACTOR,
            },
        }

    def update_references(self) -> None:
        for facility_type in self.facilities.values():
            for addon_type in facility_type.values():
                facility: Facility
                for facility in addon_type:
                    try:
                        facility.unit = self.get_updated_unit_reference(facility.unit)
                    except UnitReferenceMixin.UnitNotFound:
                        addon_type.remove(facility)

    def get_builder(self, unit_type: UnitTypeId) -> Unit:
        candidates = []
        builder_type: UnitTypeId = self.get_cheapest_builder_type(unit_type)
        usable_add_ons: list[UnitTypeId]
        if unit_type in self.needs_tech_lab:
            usable_add_ons = [UnitTypeId.TECHLAB]
        elif unit_type in self.add_on_types:
            usable_add_ons = [UnitTypeId.NOTAUNIT]
        else:
            usable_add_ons = [UnitTypeId.REACTOR, UnitTypeId.NOTAUNIT, UnitTypeId.TECHLAB]

        for add_on_type in usable_add_ons:
            candidates: list[Facility] = self.facilities[builder_type][add_on_type]
            logger.info(f"{add_on_type} facilities {candidates}")
            for candidate in candidates:
                if len(candidate.unit.orders) < candidate.capacity:
                    return candidate.unit

        return None

    def get_builder_type(self, unit_type_id):
        if unit_type_id in {
            UnitTypeId.BARRACKSREACTOR,
            UnitTypeId.BARRACKSTECHLAB,
        }:
            return {UnitTypeId.BARRACKS}
        if unit_type_id in {UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB}:
            return {UnitTypeId.FACTORY}
        if unit_type_id in {
            UnitTypeId.STARPORTREACTOR,
            UnitTypeId.STARPORTTECHLAB,
        }:
            return {UnitTypeId.STARPORT}
        return UNIT_TRAINED_FROM[unit_type_id]

    def get_cheapest_builder_type(self, unit_type_id: UnitTypeId) -> UnitTypeId:
        # XXX add hardcoded answers for sets with more than one entry
        return list(self.get_builder_type(unit_type_id))[0]

    def create_builder(self, unit_type: UnitTypeId) -> list[UnitTypeId]:
        build_list: list[UnitTypeId] = []
        builder_type: UnitTypeId = self.get_cheapest_builder_type(unit_type)
        if unit_type not in self.needs_tech_lab:
            if self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                # queue a reactor for a facility with no addon
                build_list.append(self.add_on_type_lookup[builder_type][UnitTypeId.REACTOR])
            else:
                build_list.append(builder_type)
        else:
            if not self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                # queue new facility of none availiable for a tech lab (more complicated, could sometimes move existing)
                build_list.append(builder_type)
            # queue a techlab for a facility with no addon
            build_list.append(self.add_on_type_lookup[builder_type][UnitTypeId.TECHLAB])

        return build_list

    def add_builder(self, unit: Unit) -> None:
        logger.info(f"adding builder {unit}")
        facility_type: UnitTypeId = None
        if unit.type_id in [UnitTypeId.BARRACKS, UnitTypeId.BARRACKSREACTOR, UnitTypeId.BARRACKSTECHLAB]:
            facility_type = UnitTypeId.BARRACKS
        elif unit.type_id in [UnitTypeId.FACTORY, UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB]:
            facility_type = UnitTypeId.FACTORY
        elif unit.type_id in [UnitTypeId.STARPORT, UnitTypeId.STARPORTREACTOR, UnitTypeId.STARPORTTECHLAB]:
            facility_type = UnitTypeId.STARPORT

        if facility_type is not None:
            if unit.type_id in [UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT]:
                self.facilities[facility_type][UnitTypeId.NOTAUNIT].append(Facility(unit))
                logger.info(f"adding to {facility_type}-NOTAUNIT")
            else:
                facility: Facility
                logger.info(f"checking facilities with no addon {self.facilities[facility_type][UnitTypeId.NOTAUNIT]}")
                for facility in self.facilities[facility_type][UnitTypeId.NOTAUNIT]:
                    facility.unit = self.get_updated_unit_reference(facility.unit)
                    if facility.unit.add_on_tag:
                        add_on = self.get_updated_unit_reference_by_tag(facility.unit.add_on_tag)
                        generic_type = list(UNIT_TECH_ALIAS[add_on.type_id])[0]
                        self.facilities[facility_type][generic_type].append(facility)
                        self.facilities[facility_type][UnitTypeId.NOTAUNIT].remove(facility)
                        facility.set_add_on_type(generic_type)
                        logger.info(f"adding to {facility_type}-{generic_type}")
