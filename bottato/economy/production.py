from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.constants import abilityid_to_unittypeid
from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.dicts.unit_tech_alias import UNIT_TECH_ALIAS
from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.dicts.upgrade_researched_from import UPGRADE_RESEARCHED_FROM
from sc2.game_data import Cost
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.log_helper import LogHelper
from bottato.mixins import timed, timed_async
from bottato.tech_tree import TECH_TREE
from bottato.unit_reference_helper import UnitReferenceHelper


class Facility():
    def __init__(self, bot: BotAI, unit: Unit) -> None:
        self.bot = bot
        self.unit = unit
        self.add_on_type = UnitTypeId.NOTAUNIT
        self.addon_blocked = False
        self.addon_destroyed_time: float = 0
        self.in_progress_unit: Unit | None = None
        self.capacity = 1
        self.queued_unit_ids = []
        self.new_position: Point2 | None = None
        self.was_told_to_lift_to_unblock_addon: bool = False
        self.was_lifted_to_unblock_addon: bool = False

    def __repr__(self) -> str:
        return f"facility {self.unit}-{self.add_on_type}"

    async def update_references(self) -> None:
        logger.debug(f"updating reference for facility {self}")
        try:
            updated_unit: Unit = UnitReferenceHelper.get_updated_unit_reference(self.unit)
        except UnitReferenceHelper.UnitNotFound:
            raise UnitReferenceHelper.UnitNotFound
            # addon_type.remove(facility)

        logger.debug(f"updated reference for facility {updated_unit}-{updated_unit.orders}")
        updated_unit.orders.sort(reverse=True, key=lambda order: order.progress)
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

        self.unit = updated_unit

        is_flying = self.unit.is_flying or self.unit.type_id in (UnitTypeId.BARRACKSFLYING, UnitTypeId.FACTORYFLYING, UnitTypeId.STARPORTFLYING)
        if is_flying:
            if self.was_told_to_lift_to_unblock_addon:
                self.was_lifted_to_unblock_addon = True
                self.was_told_to_lift_to_unblock_addon = False
            self.addon_blocked = False
        elif self.add_on_type == UnitTypeId.NOTAUNIT and not self.addon_blocked and not self.unit.has_add_on:
            closest_candidates = self.bot.structures.filter(lambda s: s.tag != updated_unit.tag and s.type_id not in (
                UnitTypeId.BARRACKSTECHLAB,
                UnitTypeId.BARRACKSREACTOR,
                UnitTypeId.FACTORYTECHLAB,
                UnitTypeId.FACTORYREACTOR,
                UnitTypeId.STARPORTTECHLAB,
                UnitTypeId.STARPORTREACTOR
            ))
            if not closest_candidates:
                self.addon_blocked = False
            else:
                closest_structure_to_addon = closest_candidates.closest_to(updated_unit.add_on_position)
                self.addon_blocked = closest_structure_to_addon.radius > closest_structure_to_addon.distance_to(updated_unit.add_on_position)
                # not (await self.bot.can_place_single(UnitTypeId.SUPPLYDEPOT, updated_unit.add_on_position))

        # blocking main base ramp, don't move
        is_ramp_barracks = updated_unit.type_id in (UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING) \
                    and self.bot.main_base_ramp.barracks_in_middle \
                    and updated_unit.position.manhattan_distance(self.bot.main_base_ramp.barracks_in_middle) < 3
        if self.was_lifted_to_unblock_addon:
            if not is_flying:
                self.was_lifted_to_unblock_addon = False
            if not is_ramp_barracks:
                if self.new_position is None:
                    unit_type = updated_unit.unit_alias if updated_unit.unit_alias else updated_unit.type_id
                    self.new_position = await self.bot.find_placement(unit_type, updated_unit.position, placement_step=1, addon_place=True)
                if self.new_position and updated_unit.position != self.new_position:
                    updated_unit.move(self.new_position)
                else:
                    updated_unit(AbilityId.LAND, self.new_position)
                    self.new_position = None

        if self.addon_blocked and not is_ramp_barracks:
            logger.debug(f"addon blocked for {updated_unit}")
            # move facility to an unblocked position
            self.was_told_to_lift_to_unblock_addon = True
            updated_unit(AbilityId.LIFT)

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

    def remove_queued_unit_id(self, unit_id: UnitTypeId) -> None:
        if unit_id in self.queued_unit_ids:
            self.queued_unit_ids.remove(unit_id)
        else:
            logger.debug(f"unit {unit_id} not in queued unit ids {self.queued_unit_ids}")

    def get_available_capacity(self) -> int:
        used_capacity = len(self.unit.orders) + len(self.queued_unit_ids)
        return self.capacity - used_capacity

    def is_building_addon(self) -> bool:
        for order in self.unit.orders:
            if order.ability.id in (AbilityId.BUILD_REACTOR, AbilityId.BUILD_TECHLAB):
                return True
        return False

class Production():
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.facilities: dict[UnitTypeId, dict[UnitTypeId, List[Facility]]] = {
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
            UnitTypeId.MARAUDER,
            UnitTypeId.GHOST,
            UnitTypeId.CYCLONE,
            UnitTypeId.SIEGETANK,
            UnitTypeId.THOR,
            UnitTypeId.RAVEN,
            UnitTypeId.BANSHEE,
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
        self.add_on_type_lookup: dict[UnitTypeId, dict[UnitTypeId, UnitTypeId]] = {
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
        self.townhall_tags_with_new_work_this_step: List[int] = []

    @timed_async
    async def update_references(self) -> None:
        for facility_type in self.facilities.values():
            for addon_type in facility_type.values():
                facility: Facility
                for facility in addon_type:
                    try:
                        await facility.update_references()
                    except UnitReferenceHelper.UnitNotFound:
                        addon_type.remove(facility)
                    # check if add-on was destroyed
                    if facility.unit.has_add_on and facility.add_on_type == UnitTypeId.NOTAUNIT:
                        add_on_unit = self.bot.structures.find_by_tag(facility.unit.add_on_tag)
                        if add_on_unit:
                            type_id = facility.unit.unit_alias if facility.unit.unit_alias else facility.unit.type_id
                            facility.add_on_type = UNIT_TECH_ALIAS.get(add_on_unit.type_id, {add_on_unit.type_id}).pop()
                            self.facilities[type_id][UnitTypeId.NOTAUNIT].remove(facility)
                            self.facilities[type_id][facility.add_on_type].append(facility)
                    elif not facility.unit.has_add_on and facility.add_on_type != UnitTypeId.NOTAUNIT:
                        facility.addon_destroyed_time = self.bot.time
                        type_id = facility.unit.unit_alias if facility.unit.unit_alias else facility.unit.type_id
                        self.facilities[type_id][facility.add_on_type].remove(facility)
                        self.facilities[type_id][UnitTypeId.NOTAUNIT].append(facility)
                        logger.debug(f"add-on {facility.add_on_type} destroyed for {facility.unit}")
                        facility.add_on_type = UnitTypeId.NOTAUNIT
                    if self.bot.supply_left == 0:
                        facility.queued_unit_ids.clear()
        self.townhall_tags_with_new_work_this_step.clear()

    def remove_type_from_facilty_queue(self, facility_unit: Unit, queued_type: UnitTypeId) -> None:
        if facility_unit.type_id in self.facilities.keys():
            for addon_type in self.facilities[facility_unit.type_id]:
                facility: Facility
                for facility in self.facilities[facility_unit.type_id][addon_type]:
                    if facility.unit.tag == facility_unit.tag:
                        facility.remove_queued_unit_id(queued_type)
                        return

    def get_builder(self, unit_type: UnitTypeId) -> Unit | None:
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
                # somehow is_flying isn't sufficient, also check type_id
                if candidate.unit.is_flying or candidate.unit.type_id in (UnitTypeId.BARRACKSFLYING, UnitTypeId.FACTORYFLYING, UnitTypeId.STARPORTFLYING):
                    continue
                if unit_type in self.add_on_types and (candidate.addon_blocked or self.bot.time - candidate.addon_destroyed_time < 8):
                    logger.debug(f"can't build addon {unit_type} at {candidate} - addon_blocked: {candidate.addon_blocked}, time_since_destruction: {self.bot.time - candidate.addon_destroyed_time}")
                    continue

                if candidate.has_capacity:
                    candidate.add_queued_unit_id(unit_type)
                    return candidate.unit
                else:
                    logger.debug(f"candidate {candidate.unit} has no capacity - orders: {len(candidate.unit.orders)}, queued: {len(candidate.queued_unit_ids)}, capacity: {candidate.capacity}")

        return None

    def get_research_facility(self, upgrade_id: UpgradeId) -> Unit | None:
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

    def get_builder_type(self, unit_type_id: UnitTypeId | UpgradeId):
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
        if unit_type_id == UnitTypeId.SCV:
            return {UnitTypeId.COMMANDCENTER}
        if unit_type_id == UnitTypeId.REFINERYRICH:
            return {UnitTypeId.SCV}
        return UNIT_TRAINED_FROM[unit_type_id]
    
    costs: dict[UnitTypeId | UpgradeId, Cost] = {}
    
    def subtract_costs(self, cost: Cost, types: List[UnitTypeId]) -> Cost:
        for unit_type in types:
            if unit_type not in self.costs:
                self.costs[unit_type] = self.bot.calculate_cost(unit_type)
            unit_cost: Cost = self.costs[unit_type]
            cost.minerals -= unit_cost.minerals
            cost.vespene -= unit_cost.vespene
        return cost

    def get_cheapest_builder_type(self, unit_type_id: UnitTypeId | UpgradeId) -> UnitTypeId:
        # XXX add hardcoded answers for sets with more than one entry
        return list(self.get_builder_type(unit_type_id))[0]

    def get_build_capacity(self, builder_type: UnitTypeId, tech_lab_required: bool = False) -> int:
        capacity = 0
        if tech_lab_required:
            for facility in self.facilities[builder_type][UnitTypeId.TECHLAB]:
                capacity += facility.get_available_capacity()
        else:
            for addon_type in self.facilities[builder_type].values():
                for facility in addon_type:
                    capacity += facility.get_available_capacity()
        return capacity
    
    def can_build_any(self, unit_types: List[UnitTypeId | UpgradeId]) -> bool:
        for unit_type in unit_types:
            builder_type: UnitTypeId = self.get_cheapest_builder_type(unit_type)
            tech_lab_required: bool = False
            if unit_type in self.needs_tech_lab:
                tech_lab_required = True
            if builder_type == UnitTypeId.COMMANDCENTER:
                return self.bot.townhalls.ready.idle.amount > 0
            if self.get_build_capacity(builder_type, tech_lab_required) > 0:
                return True
        return False
    
    def get_readiness_to_build(self, unit_type: UnitTypeId) -> float:
        # returns a float between 0.0 and 1.0 representing how ready we are to build any of the given unit types
        # if a structure is under construction or working on an earlier order, return build/order progress
        # returns maximum readiness among all unit types
        max_readiness = 0.0
        
        builder_type: UnitTypeId = self.get_cheapest_builder_type(unit_type)
        tech_lab_required: bool = unit_type in self.needs_tech_lab
        
        if builder_type == UnitTypeId.COMMANDCENTER:
            if self.bot.townhalls.ready.idle.filter(lambda th: th.tag not in self.townhall_tags_with_new_work_this_step and not th.is_flying).amount > 0:
                max_readiness = 1.0
            else:
                # Check if any are under construction or busy
                for th in self.bot.townhalls:
                    if th.is_flying:
                        max_readiness = max(max_readiness, 0.8)
                    if not th.is_ready:
                        max_readiness = max(max_readiness, th.build_progress)
                    elif not th.is_idle and th.orders:
                        # Estimate progress based on first order
                        order_progress = th.orders[0].progress
                        max_readiness = max(max_readiness, order_progress)
        else:
            addon_types: List[UnitTypeId] = []
            if tech_lab_required:
                addon_types = [UnitTypeId.TECHLAB]
            elif unit_type in self.add_on_types:
                addon_types = [UnitTypeId.NOTAUNIT]
            else:
                addon_types = [UnitTypeId.REACTOR, UnitTypeId.NOTAUNIT, UnitTypeId.TECHLAB]
            for addon_type in addon_types:
                facilities = self.facilities.get(builder_type, {}).get(addon_type, [])
                
                for facility in facilities:                        
                    # Facility is flying (moving to new position)
                    if facility.unit.is_flying:
                        max_readiness = max(max_readiness, 0.8)
                        continue
                    
                    # Facility has available capacity
                    if facility.has_capacity:
                        max_readiness = 1.0
                        break
                    
                    # Facility is busy but has orders - estimate progress
                    max_orders = 2 if addon_type == UnitTypeId.REACTOR else 1
                    num_orders = len(facility.unit.orders)
                    if num_orders > max_orders or num_orders == 0:
                        # has an order queued, readiness is 0
                        continue
                
                    # Use the most progressed order as readiness indicator
                    most_progressed = max(order.progress for order in facility.unit.orders)
                    max_readiness = max(max_readiness, most_progressed)
            
            # Check if builder structure itself needs to be built
            if max_readiness < 1.0:
                builder_structures = self.bot.structures(builder_type)
                if not builder_structures.ready:
                    # Structure under construction
                    for structure in builder_structures:
                        max_readiness = max(max_readiness, structure.build_progress)
        
        return max_readiness

    @timed
    def additional_needed_production(self, unit_types: List[UnitTypeId]):
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
                production_capacity[builder_type]["tech"]["available"] += facility.get_available_capacity()
            for facility in self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                production_capacity[builder_type]["normal"]["available"] += facility.get_available_capacity()
            for facility in self.facilities[builder_type][UnitTypeId.REACTOR]:
                production_capacity[builder_type]["normal"]["available"] += facility.get_available_capacity()

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
        needed_resources: Cost = Cost(self.bot.minerals, self.bot.vespene)
        additional_production: List[UnitTypeId | UpgradeId] = []
        prereqs_added: List[UnitTypeId] = []
        for builder_type in self.facilities.keys():
            production_capacity[builder_type]["tech"]["net"] = production_capacity[builder_type]["tech"]["available"] - production_capacity[builder_type]["tech"]["needed"]
            production_capacity[builder_type]["normal"]["net"] = production_capacity[builder_type]["normal"]["available"] - production_capacity[builder_type]["normal"]["needed"]
            tech_balance = production_capacity[builder_type]["tech"]["net"]
            normal_balance = production_capacity[builder_type]["normal"]["net"]

            if tech_balance < 0:
                for i in range(abs(tech_balance)):
                    if needed_resources.minerals < 0 or needed_resources.vespene < 0:
                        logger.debug("not enough resources to build additional tech lab")
                        break
                    facility: Facility
                    # look for facility with no add-on to upgrade
                    for facility in self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                        if facility.is_building_addon():
                            continue
                        if facility.unit.tag not in upgraded_facility_tags[builder_type]:
                            upgraded_facility_tags[builder_type].append(facility.unit.tag)
                            break
                    else:
                        if builder_type in prereqs_added:
                            additional_production.append(builder_type)
                        else:
                            additional_production.extend(self.build_order_with_prereqs(builder_type))
                            prereqs_added.append(builder_type)
                        needed_resources = self.subtract_costs(needed_resources, [builder_type])
                    additional_production.append(self.add_on_type_lookup[builder_type][UnitTypeId.TECHLAB])
                    needed_resources = self.subtract_costs(needed_resources, [UnitTypeId.TECHLAB])

            # use leftover tech facilities
            if tech_balance > 0:
                normal_balance += tech_balance
            extra_facility = False

            if normal_balance < 0:
                for i in range(abs(normal_balance)):
                    if needed_resources.minerals < 0 or needed_resources.vespene < 0:
                        logger.debug("not enough resources to build additional reactor/facility")
                        break
                    facility: Facility
                    for facility in self.facilities[builder_type][UnitTypeId.NOTAUNIT]:
                        if facility.is_building_addon():
                            continue
                        if facility.unit.tag not in upgraded_facility_tags[builder_type] and not facility.addon_blocked:
                            upgraded_facility_tags[builder_type].append(facility.unit.tag)
                            additional_production.append(self.add_on_type_lookup[builder_type][UnitTypeId.REACTOR])
                            needed_resources = self.subtract_costs(needed_resources, [UnitTypeId.REACTOR])
                            break
                    else:
                        if extra_facility:
                            additional_production.append(self.add_on_type_lookup[builder_type][UnitTypeId.REACTOR])
                            needed_resources = self.subtract_costs(needed_resources, [UnitTypeId.REACTOR])
                            extra_facility = False
                        else:
                            if builder_type in prereqs_added:
                                additional_production.append(builder_type)
                            else:
                                additional_production.extend(self.build_order_with_prereqs(builder_type))
                                prereqs_added.append(builder_type)
                            needed_resources = self.subtract_costs(needed_resources, [builder_type])
                            extra_facility = True

        logger.debug(f"production capacity {production_capacity}")
        logger.debug(f"additional production {additional_production}")
        return additional_production

    def add_builder(self, unit: Unit) -> None:
        facility_type: UnitTypeId | None = None
        if unit.type_id in [UnitTypeId.BARRACKS, UnitTypeId.BARRACKSREACTOR, UnitTypeId.BARRACKSTECHLAB]:
            facility_type = UnitTypeId.BARRACKS
        elif unit.type_id in [UnitTypeId.FACTORY, UnitTypeId.FACTORYREACTOR, UnitTypeId.FACTORYTECHLAB]:
            facility_type = UnitTypeId.FACTORY
        elif unit.type_id in [UnitTypeId.STARPORT, UnitTypeId.STARPORTREACTOR, UnitTypeId.STARPORTTECHLAB]:
            facility_type = UnitTypeId.STARPORT

        if facility_type is not None:
            logger.debug(f"adding builder {unit}")
            if unit.type_id in [UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT]:
                new_facility = Facility(self.bot, unit)
                self.facilities[facility_type][UnitTypeId.NOTAUNIT].append(new_facility)
                logger.debug(f"added {unit} to {facility_type}-NOTAUNIT, total facilities: {len(self.facilities[facility_type][UnitTypeId.NOTAUNIT])}")
            else:
                facility: Facility
                logger.debug(f"checking facilities with no addon {self.facilities[facility_type][UnitTypeId.NOTAUNIT]}")
                for facility in self.facilities[facility_type][UnitTypeId.NOTAUNIT]:
                    try:
                        facility.unit = UnitReferenceHelper.get_updated_unit_reference(facility.unit)
                    except UnitReferenceHelper.UnitNotFound:
                        continue
                    if facility.unit.add_on_tag:
                        add_on = UnitReferenceHelper.get_updated_unit_reference_by_tag(facility.unit.add_on_tag)
                        generic_type = list(UNIT_TECH_ALIAS[add_on.type_id])[0] if add_on.type_id not in (UnitTypeId.TECHLAB, UnitTypeId.REACTOR) else add_on.type_id
                        self.facilities[facility_type][generic_type].append(facility)
                        self.facilities[facility_type][UnitTypeId.NOTAUNIT].remove(facility)
                        facility.set_add_on_type(generic_type)
                        logger.debug(f"adding to {facility_type}-{generic_type}")

    def build_order_with_prereqs(self, unit_type: UnitTypeId | UpgradeId) -> List[UnitTypeId | UpgradeId]:
        build_order = self.build_order_with_prereqs_recurse(unit_type)
        build_order.reverse()
        return build_order

    def build_order_with_prereqs_recurse(self,
                                         unit_type: UnitTypeId | UpgradeId | None,
                                         previous_types: List[UnitTypeId | UpgradeId] | None= None) -> List[UnitTypeId | UpgradeId]:
        if unit_type is None:
            return []
        if previous_types is None:
            previous_types = []
        else:
            if unit_type in previous_types:
                return []
            elif isinstance(unit_type, UnitTypeId) and self.bot.structure_type_build_progress(unit_type) > 0:
                return []
            elif isinstance(unit_type, UpgradeId) and self.bot.already_pending_upgrade(unit_type):
                return []
        build_order: List[UnitTypeId | UpgradeId] = [unit_type]
        previous_types.append(unit_type)

        if isinstance(unit_type, UpgradeId):
            requirement = UPGRADE_RESEARCHED_FROM[unit_type]
            build_order += self.build_order_with_prereqs_recurse(requirement, previous_types)

            research_structure_type: UnitTypeId = UPGRADE_RESEARCHED_FROM[unit_type]
            required_tech_building: UnitTypeId | None = RESEARCH_INFO[research_structure_type][unit_type].get(
                "required_building", None
            ) # type: ignore
            build_order += self.build_order_with_prereqs_recurse(required_tech_building, previous_types)
        else:
            if unit_type in TECH_TREE:
                # check that all tech requirements are met
                for requirement in TECH_TREE[unit_type]:
                    build_order += self.build_order_with_prereqs_recurse(requirement, previous_types)

            if unit_type in UNIT_TRAINED_FROM:
                # check that one training facility exists
                for trainer in UNIT_TRAINED_FROM[unit_type]:
                    if trainer in previous_types:
                        break
                    if trainer == UnitTypeId.SCV and self.bot.workers:
                        break
                    if self.bot.structure_type_build_progress(trainer) > 0:
                        break
                else:
                    # no trainers available
                    for trainer in UNIT_TRAINED_FROM[unit_type]:
                        requirement_bom = self.build_order_with_prereqs_recurse(trainer, previous_types)
                        if requirement_bom:
                            build_order.extend(requirement_bom)
                            break
                    else:
                        return []

        return build_order

    async def set_addon_blocked(self, blocked_facility: Unit, interrupted_count: int) -> bool:
        facility: Facility
        for facility in self.facilities[blocked_facility.type_id][UnitTypeId.NOTAUNIT]:
            if facility.unit.tag == blocked_facility.tag:
                # if it's been interrupted too many times despite not registering as blocked, mark it anyways
                if interrupted_count > 20:
                    LogHelper.add_log(f"marking {facility} as blocked after {interrupted_count} interruptions")
                    facility.addon_blocked = True
                    return True
                # check that it isn't blocked by an enemy unit
                if not self.bot.enemy_units.closer_than(1, facility.unit.add_on_position) and not self.bot.units.closer_than(1, facility.unit.add_on_position):
                    if not await self.bot.can_place_single(UnitTypeId.SUPPLYDEPOT, facility.unit.add_on_position):
                        facility.addon_blocked = True
                        return True
                    else:
                        LogHelper.add_log(f"addon position for {facility.unit} is not actually blocked")
                break
        return False
