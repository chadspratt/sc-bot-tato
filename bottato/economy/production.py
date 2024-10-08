from typing import List, Union
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit, UnitOrder
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.constants import abilityid_to_unittypeid

from ..mixins import UnitReferenceMixin
from ..tech_tree import TECH_TREE


class Facility(UnitReferenceMixin):
    def __init__(self, bot: BotAI, unit: Unit) -> None:
        self.bot = bot
        self.unit = unit
        self.add_on_type = UnitTypeId.NOTAUNIT
        self.addon_blocked = False
        self.addon_destroyed_time = None
        self.in_progress_unit: Unit = None
        self.capacity = 1
        self.queued_unit_ids = []

    def __repr__(self) -> str:
        return f"facility {self.unit}-{self.add_on_type}"

    async def update_references(self) -> None:
        logger.debug(f"updating reference for facility {self}")
        try:
            updated_unit: Unit = self.get_updated_unit_reference(self.unit)
        except UnitReferenceMixin.UnitNotFound:
            raise UnitReferenceMixin.UnitNotFound
            # addon_type.remove(facility)

        logger.debug(f"updated reference for facility {updated_unit}-{updated_unit.orders}")
        updated_unit.orders.sort(reverse=True, key=Facility.order_sort_key)
        for new_order in updated_unit.orders:
            for old_order in self.unit.orders:
                if new_order.progress > old_order.progress:
                    self.unit.orders.remove(old_order)
                    break
            else:
                logger.debug(f"new order {new_order}")
                # new order doesn't match any old, must be new
                try:
                    new_unit_id: UnitTypeId = abilityid_to_unittypeid[new_order.ability.id]
                    for queued_unit_id in self.queued_unit_ids:
                        if queued_unit_id == new_unit_id:
                            logger.debug(f"new order matched {queued_unit_id}")
                            self.queued_unit_ids.remove(queued_unit_id)
                            break
                    else:
                        logger.debug(f"no match for {new_order}")
                except KeyError:
                    # add-on
                    logger.debug(f"key error, is this an addon?: {new_order}")
                    self.queued_unit_ids.clear()

        if self.add_on_type == UnitTypeId.NOTAUNIT and not self.addon_blocked:
            closest_structure_to_addon = self.bot.structures.closest_to(updated_unit.add_on_position)
            self.addon_blocked = closest_structure_to_addon.radius > closest_structure_to_addon.distance_to(updated_unit.add_on_position)
            # not (await self.bot.can_place_single(UnitTypeId.SUPPLYDEPOT, updated_unit.add_on_position))
            if self.addon_blocked:
                logger.info(f"addon blocked for {updated_unit}")

        self.unit = updated_unit

    def order_sort_key(order: UnitOrder) -> float:
        return order.progress

    @property
    def has_capacity(self) -> bool:
        logger.debug(f"facility has orders {self.unit.orders} + {self.queued_unit_ids} and capacity {self.capacity}")
        return len(self.unit.orders) + len(self.queued_unit_ids) < self.capacity

    def set_add_on_type(self, add_on_type: UnitTypeId) -> None:
        self.add_on_type = add_on_type
        if add_on_type == UnitTypeId.REACTOR:
            self.capacity = 2

    def add_queued_unit_id(self, unit_id: UnitTypeId) -> None:
        self.queued_unit_ids.append(unit_id)


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
        self.needs_tech_lab: List[UnitTypeId] = [
            UnitTypeId.RAVEN,
            UnitTypeId.BANSHEE,
            UnitTypeId.SIEGETANK,
            UnitTypeId.BATTLECRUISER
        ]
        self.add_on_types: List[UnitTypeId] = [
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

    async def update_references(self) -> None:
        for facility_type in self.facilities.values():
            for addon_type in facility_type.values():
                facility: Facility
                for facility in addon_type:
                    try:
                        await facility.update_references()
                    except UnitReferenceMixin.UnitNotFound:
                        addon_type.remove(facility)
                    if self.bot.supply_left == 0:
                        facility.queued_unit_ids.clear()

    def get_builder(self, unit_type: UnitTypeId) -> Unit:
        candidates = []
        builder_type: UnitTypeId = self.get_cheapest_builder_type(unit_type)
        usable_add_ons: List[UnitTypeId]
        if unit_type in self.needs_tech_lab:
            usable_add_ons = [UnitTypeId.TECHLAB]
        elif unit_type in self.add_on_types:
            usable_add_ons = [UnitTypeId.NOTAUNIT]
        else:
            usable_add_ons = [UnitTypeId.REACTOR, UnitTypeId.NOTAUNIT, UnitTypeId.TECHLAB]

        for add_on_type in usable_add_ons:
            candidates: List[Facility] = self.facilities[builder_type][add_on_type]
            logger.debug(f"{add_on_type} facilities {candidates}")
            for candidate in candidates:
                if unit_type in self.add_on_types and candidate.addon_blocked:
                    logger.info(f"can't build addon {unit_type} at {candidate}")
                    continue

                if candidate.has_capacity:
                    candidate.add_queued_unit_id(unit_type)
                    return candidate.unit
                else:
                    logger.info

        return None

    def get_research_facility(self, upgrade_id: UpgradeId) -> Unit:
        research_structure_type: UnitTypeId = UPGRADE_RESEARCHED_FROM[upgrade_id]

        structure: Unit
        for structure in self.bot.structures:
            if (
                # Structure can research this upgrade
                structure.type_id == research_structure_type
                and structure.is_ready
                # If structure hasn't received an action/order this frame
                and structure.tag not in self.bot.unit_tags_received_action
                # Structure is idle
                and structure.is_idle
            ):
                return structure
        return None

    def get_builder_type(self, unit_type_id: Union[UnitTypeId, UpgradeId]):
        if isinstance(unit_type_id, UpgradeId):
            return {UPGRADE_RESEARCHED_FROM[unit_type_id]}
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

    def get_cheapest_builder_type(self, unit_type_id: Union[UnitTypeId, UpgradeId]) -> UnitTypeId:
        # XXX add hardcoded answers for sets with more than one entry
        return list(self.get_builder_type(unit_type_id))[0]

    def additional_needed_production(self, unit_types: List[Union[UnitTypeId, UpgradeId]]):
        production_capacity = {
            UnitTypeId.BARRACKS: {
                "tech": {
                    "available": 0,
                    "needed": 0,
                    "net": 0,
                },
                "normal": {
                    "available": 0,
                    "needed": 0,
                    "net": 0,
                }
            },
            UnitTypeId.FACTORY: {
                "tech": {
                    "available": 0,
                    "needed": 0,
                    "net": 0,
                },
                "normal": {
                    "available": 0,
                    "needed": 0,
                    "net": 0,
                }
            },
            UnitTypeId.STARPORT: {
                "tech": {
                    "available": 0,
                    "needed": 0,
                    "net": 0,
                },
                "normal": {
                    "available": 0,
                    "needed": 0,
                    "net": 0,
                }
            },
        }
        for builder_type in self.facilities.keys():
            for facility in self.facilities[builder_type][UnitTypeId.TECHLAB]:
                used_capacity = len(facility.unit.orders) + len(facility.queued_unit_ids)
                production_capacity[builder_type]["tech"]["available"] += facility.capacity - used_capacity

            for facility in self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                used_capacity = len(facility.unit.orders) + len(facility.queued_unit_ids)
                production_capacity[builder_type]["normal"]["available"] += facility.capacity - used_capacity
            for facility in self.facilities[builder_type][UnitTypeId.REACTOR]:
                used_capacity = len(facility.unit.orders) + len(facility.queued_unit_ids)
                production_capacity[builder_type]["normal"]["available"] += facility.capacity - used_capacity

        for unit_type in unit_types:
            if isinstance(unit_type, UpgradeId):
                continue
            if unit_type in self.add_on_types:
                continue
            builder_type = self.get_cheapest_builder_type(unit_type)
            if builder_type not in production_capacity.keys():
                continue
            if unit_type in self.needs_tech_lab:
                production_capacity[builder_type]["tech"]["needed"] += 1
            else:
                production_capacity[builder_type]["normal"]["needed"] += 1

        upgraded_facility_tags = {
            UnitTypeId.BARRACKS: [],
            UnitTypeId.FACTORY: [],
            UnitTypeId.STARPORT: [],
        }
        additional_production: List[UnitTypeId] = []
        prereqs_added: List[UnitTypeId] = []
        for builder_type in self.facilities.keys():
            production_capacity[builder_type]["tech"]["net"] = production_capacity[builder_type]["tech"]["available"] - production_capacity[builder_type]["tech"]["needed"]
            production_capacity[builder_type]["normal"]["net"] = production_capacity[builder_type]["normal"]["available"] - production_capacity[builder_type]["normal"]["needed"]
            tech_balance = production_capacity[builder_type]["tech"]["net"]
            normal_balance = production_capacity[builder_type]["normal"]["net"]

            if tech_balance < 0:
                for i in range(abs(tech_balance)):
                    facility: Facility
                    # look for facility with no add-on to upgrade
                    for facility in self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                        if facility.unit.tag not in upgraded_facility_tags[builder_type]:
                            upgraded_facility_tags[builder_type].append(facility.unit.tag)
                            break
                    else:
                        if builder_type in prereqs_added:
                            additional_production.append(builder_type)
                        else:
                            additional_production.extend(self.build_order_with_prereqs(builder_type))
                            prereqs_added.append(builder_type)
                    additional_production.append(self.add_on_type_lookup[builder_type][UnitTypeId.TECHLAB])

            # use leftover tech facilities
            if tech_balance > 0:
                normal_balance += tech_balance
            extra_facility = False

            if normal_balance < 0:
                for i in range(abs(normal_balance)):
                    facility: Facility
                    for facility in self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                        if facility.unit.tag not in upgraded_facility_tags[builder_type] and not facility.addon_blocked:
                            upgraded_facility_tags[builder_type].append(facility.unit.tag)
                            additional_production.append(self.add_on_type_lookup[builder_type][UnitTypeId.REACTOR])
                            break
                    else:
                        if extra_facility:
                            additional_production.append(self.add_on_type_lookup[builder_type][UnitTypeId.REACTOR])
                            extra_facility = False
                        else:
                            if builder_type in prereqs_added:
                                additional_production.append(builder_type)
                            else:
                                additional_production.extend(self.build_order_with_prereqs(builder_type))
                                prereqs_added.append(builder_type)
                            extra_facility = True

        logger.debug(f"production capacity {production_capacity}")
        logger.debug(f"additional production {additional_production}")
        return additional_production

    def create_builder(self, unit_type: UnitTypeId) -> List[UnitTypeId]:
        build_list: List[UnitTypeId] = []
        builder_type: UnitTypeId = self.get_cheapest_builder_type(unit_type)
        if unit_type in self.needs_tech_lab:
            if self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                facility: Facility
                for facility in self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                    if not facility.addon_blocked:
                        # queue a techlab for a facility with no addon
                        build_list.append(self.add_on_type_lookup[builder_type][UnitTypeId.TECHLAB])
                        break
        elif self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
            facility: Facility
            for facility in self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                if not facility.addon_blocked:
                    # queue a reactor for a facility with no addon
                    build_list.append(self.add_on_type_lookup[builder_type][UnitTypeId.REACTOR])
                    break

        if not build_list:
            # queue new facility of none availiable for an addon
            build_list.append(builder_type)
            if unit_type in self.needs_tech_lab:
                build_list.append(self.add_on_type_lookup[builder_type][UnitTypeId.TECHLAB])

        return build_list

    def add_builder(self, unit: Unit) -> None:
        facility_type: UnitTypeId = None
        if unit.type_id in [UnitTypeId.BARRACKS, UnitTypeId.BARRACKSREACTOR, UnitTypeId.BARRACKSTECHLAB]:
            facility_type = UnitTypeId.BARRACKS
        elif unit.type_id in [UnitTypeId.FACTORY, UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB]:
            facility_type = UnitTypeId.FACTORY
        elif unit.type_id in [UnitTypeId.STARPORT, UnitTypeId.STARPORTREACTOR, UnitTypeId.STARPORTTECHLAB]:
            facility_type = UnitTypeId.STARPORT

        if facility_type is not None:
            logger.info(f"adding builder {unit}")
            if unit.type_id in [UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT]:
                self.facilities[facility_type][UnitTypeId.NOTAUNIT].append(Facility(self.bot, unit))
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

    def build_order_with_prereqs(self, unit_type: Union[UnitTypeId, UpgradeId]) -> List[Union[UnitTypeId, UpgradeId]]:
        build_order = self.build_order_with_prereqs_recurse(unit_type)
        build_order.reverse()
        return build_order

    def build_order_with_prereqs_recurse(self,
                                         unit_type: Union[UnitTypeId, UpgradeId],
                                         previous_types: List[Union[UnitTypeId, UpgradeId]] = []) -> List[Union[UnitTypeId, UpgradeId]]:
        build_order = [unit_type]
        new_previous = [unit_type]
        new_previous.extend(previous_types)

        if isinstance(unit_type, UpgradeId):
            requirement = UPGRADE_RESEARCHED_FROM[unit_type]
            prereq_progress = self.bot.structure_type_build_progress(requirement)
            logger.debug(f"{requirement} progress: {prereq_progress}")

            if prereq_progress == 0:
                requirement_bom = self.build_order_with_prereqs_recurse(requirement, new_previous)
                # if same prereq appears at a higher level, skip adding it
                if unit_type in requirement_bom:
                    build_order = requirement_bom
                else:
                    build_order.extend(requirement_bom)
        else:
            if unit_type in TECH_TREE:
                # check that all tech requirements are met
                for requirement in TECH_TREE[unit_type]:
                    prereq_progress = self.bot.structure_type_build_progress(requirement)
                    logger.debug(f"{requirement} progress: {prereq_progress}")

                    if prereq_progress == 0:
                        requirement_bom = self.build_order_with_prereqs_recurse(requirement, new_previous)
                        # if same prereq appears at a higher level, skip adding it
                        if unit_type in requirement_bom:
                            build_order = requirement_bom
                        else:
                            build_order.extend(requirement_bom)

            if unit_type in UNIT_TRAINED_FROM:
                # check that one training facility exists
                for trainer in UNIT_TRAINED_FROM[unit_type]:
                    if trainer in build_order:
                        break
                    if trainer == UnitTypeId.SCV and self.bot.workers:
                        break
                    if self.bot.structure_type_build_progress(trainer) > 0:
                        break
                else:
                    # no trainers available
                    for trainer in UNIT_TRAINED_FROM[unit_type]:
                        if trainer not in previous_types:
                            requirement_bom = self.build_order_with_prereqs_recurse(trainer, new_previous)
                            if requirement_bom:
                                build_order.extend(requirement_bom)
                                break
                    else:
                        return []

        return build_order

    def get_no_addon_facilities(self) -> List[Unit]:
        return [facility.unit for facility in
                self.facilities[UnitTypeId.BARRACKS][UnitTypeId.NOTAUNIT]
                + self.facilities[UnitTypeId.FACTORY][UnitTypeId.NOTAUNIT]
                + self.facilities[UnitTypeId.STARPORT][UnitTypeId.NOTAUNIT]]
