import math
from loguru import logger
from typing import Dict

from cython_extensions.geometry import cy_distance_to, cy_distance_to_squared
from cython_extensions.type_checking.wrappers import cy_towards
from cython_extensions.units_utils import cy_closer_than, cy_closest_to
from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.protocol import ConnectionAlreadyClosedError, ProtocolError
from sc2.unit import Unit
from sc2.unit_command import UnitCommand
from sc2.units import Units

from bottato.building.build_step import BuildStep
from bottato.building.special_locations import SpecialLocations
from bottato.economy.production import Production
from bottato.economy.workers import Workers
from bottato.enums import (
    BuildResponseCode,
    BuildType,
    ExpansionSelection,
    UnitMicroType,
    WorkerJobType,
)
from bottato.log_helper import LogHelper
from bottato.map.destructibles import BUILDING_RADIUS
from bottato.map.map import Map
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import timed, timed_async
from bottato.tech_tree import TECH_TREE
from bottato.unit_reference_helper import UnitReferenceHelper
from bottato.unit_types import UnitTypes


class SCVBuildStep(BuildStep):
    unit_type_id: UnitTypeId
    position: Point2 | None = None
    unit_being_built: Unit | None = None
    geysir: Unit | None = None
    worker_in_position_time: float | None = None
    no_position_count: int = 0

    def __init__(self, unit_type_id: UnitTypeId, bot: BotAI, workers: Workers, production: Production, map: Map) -> None:
        super().__init__(unit_type_id, bot, workers, production, map)
        if unit_type_id == UnitTypeId.REFINERYRICH:
            unit_type_id = UnitTypeId.REFINERY
        self.unit_type_id = unit_type_id

    def __repr__(self) -> str:
        builder = self.unit_in_charge if self.unit_in_charge else self.builder_type
        target = ""
        if self.unit_being_built:
            target = f"{self.unit_being_built} {self.unit_being_built.build_progress}"
        else:
            target = self.unit_type_id.name

        return f"{target}-built by {builder}"

    def update_references(self):
        logger.debug(f"unit in charge: {self.unit_in_charge}")
        if self.unit_in_charge:
            try:
                self.unit_in_charge = UnitReferenceHelper.get_updated_unit_reference(self.unit_in_charge)
            except UnitReferenceHelper.UnitNotFound:
                self.unit_in_charge = None
        if self.geysir:
            try:
                self.geysir = UnitReferenceHelper.get_updated_unit_reference(self.geysir)
            except UnitReferenceHelper.UnitNotFound:
                self.geysir = None
        if self.unit_being_built:
            try:
                self.unit_being_built = UnitReferenceHelper.get_updated_unit_reference(self.unit_being_built)
            except UnitReferenceHelper.UnitNotFound:
                self.unit_being_built = None

    @timed
    def draw_debug_box(self):
        if self.unit_in_charge is not None:
            self.bot.client.debug_sphere_out(self.unit_in_charge, 1, (255, 130, 0))
            if self.position:
                self.bot.client.debug_line_out(self.unit_in_charge, self.convert_point2_to_3(self.position, self.bot), (255, 130, 0))
            if self.unit_type_id:
                self.bot.client.debug_text_world(
                    self.unit_type_id.name, self.unit_in_charge.position3d)
        if self.position:
            self.bot.client.debug_box2_out(self.convert_point2_to_3(self.position, self.bot), 0.5)
            if self.unit_type_id is not None:
                self.bot.client.debug_text_world(
                    self.unit_type_id.name, self.convert_point2_to_3(self.position, self.bot)
                )
    
    def is_unit_type(self, unit_type_id: UnitTypeId | UpgradeId) -> bool:
        if isinstance(unit_type_id, UpgradeId):
            return False
        if unit_type_id in (UnitTypeId.REFINERY, UnitTypeId.REFINERYRICH):
            return self.unit_type_id in (UnitTypeId.REFINERY, UnitTypeId.REFINERYRICH)
        return self.unit_type_id == unit_type_id
    
    def is_unit_production_facility(self) -> bool:
        return self.unit_type_id in (
            UnitTypeId.BARRACKS,
            UnitTypeId.FACTORY,
            UnitTypeId.STARPORT,
        )

    def get_unit_type_id(self) -> UnitTypeId:
        return self.unit_type_id
    
    def get_structure_being_built(self) -> Unit | None:
        return self.unit_being_built
    
    def set_unit_being_built(self, unit: Unit):
        self.unit_being_built = unit
        self.position = unit.position
    
    def is_same_structure(self, structure: Unit) -> bool:
        if self.unit_being_built and self.unit_being_built.tag == structure.tag:
            return True
        if self.position and self.bot.distance_math_hypot_squared(structure.position, self.position) < 2.25: # 1.5 squared
            return True
        return False
    
    def manhattan_distance(self, point: Point2) -> float:
        if self.position:
            return self.position.manhattan_distance(point)
        return 9999
    
    def has_position_reserved(self) -> bool:
        return self.position is not None and self.unit_being_built is None

    def get_position(self) -> Point2 | None:
        return self.position
    
    def tech_requirements_met(self) -> bool:
        if self.unit_type_id in TECH_TREE:
            # check that all tech requirements are met
            for requirement in TECH_TREE[self.unit_type_id]:
                if self.bot.structure_type_build_progress(requirement) < 0.8:
                    return False
        return True

    async def execute(self, special_locations: SpecialLocations, detected_enemy_builds: Dict[BuildType, float], floating_building_destinations: Dict[int, Point2]) -> BuildResponseCode:
        response = await self.execute_scv_build(special_locations, detected_enemy_builds, floating_building_destinations)
            
        if response == BuildResponseCode.SUCCESS:
            self.is_in_progress = True
        return response
    
    @timed_async
    async def execute_scv_build(self, special_locations: SpecialLocations, detected_enemy_builds: Dict[BuildType, float], floating_building_destinations: Dict[int, Point2]) -> BuildResponseCode:
        if self.unit_type_id == UnitTypeId.REFINERYRICH:
            self.unit_type_id = UnitTypeId.REFINERY
        if self.unit_being_built:
            self.position = self.unit_being_built.position
            if self.start_time == 0:
                self.start_time = self.bot.time
        else:
            if self.unit_type_id == UnitTypeId.REFINERY:
                # Vespene targets unit to build instead of position
                self.geysir: Unit | None = self.get_geysir()
                if self.geysir is None:
                    return BuildResponseCode.NO_FACILITY
                self.position = self.geysir.position
            else:
                # try to reset position to highground if it was set to low before rush was detected
                # if self.unit_type_id == UnitTypeId.BUNKER and BuildType.RUSH in detected_enemy_builds and self.unit_being_built is None:
                #     self.position = None
                if self.position is None or (self.start_time != 0 and self.bot.time - self.start_time > 3 and self.bot.minerals >= self.cost.minerals and self.bot.vespene >= self.cost.vespene):
                    self.position = await self.find_placement(self.unit_type_id, special_locations, detected_enemy_builds, floating_building_destinations)
                if self.position is None:
                    self.no_position_count += 1
                    return BuildResponseCode.NO_LOCATION

        self.unit_in_charge = self.workers.get_builder(self.position, self.unit_in_charge)
        if self.unit_in_charge is None:
            return BuildResponseCode.NO_BUILDER

        threats = self.bot.enemy_units.filter(
            lambda u: u.type_id not in UnitTypes.WORKER_TYPES \
                and UnitTypes.can_attack_ground(u))
        enemy_is_close = self.unit_is_closer_than(self.unit_in_charge, threats, 15)
        if self.unit_being_built and not enemy_is_close:
            enemy_is_close = self.unit_is_closer_than(self.unit_being_built, threats, 10)
        if enemy_is_close:
            return BuildResponseCode.TOO_CLOSE_TO_ENEMY

        build_response: bool | UnitCommand
        if self.unit_being_built:
            build_response = self.unit_in_charge.smart(self.unit_being_built)
        else:
            if self.unit_type_id == UnitTypeId.REFINERY and self.geysir:
                build_response = self.unit_in_charge.build_gas(self.geysir)
            else:
                build_response = self.unit_in_charge.build(
                    self.unit_type_id, self.position
                )

        if build_response:
            self.start_time = self.bot.time
            return BuildResponseCode.SUCCESS
        return BuildResponseCode.FAILED
    
    def set_position(self, x, y):
        self.position = Point2((x, y))

    async def position_worker(self,
                              special_locations: SpecialLocations,
                              detected_enemy_builds: Dict[BuildType, float],
                              flying_building_destinations: Dict[int, Point2]):
        if UnitTypeId.SCV in self.builder_type:
            if self.unit_type_id == UnitTypeId.REFINERYRICH:
                self.unit_type_id = UnitTypeId.REFINERY
            if self.position is None:
                if self.unit_type_id == UnitTypeId.REFINERY:
                    # Vespene targets unit to build instead of position
                    self.geysir: Unit | None = self.get_geysir()
                    if self.geysir is None:
                        return
                    self.position = self.geysir.position
                else:
                    self.position = await self.find_placement(self.unit_type_id, special_locations, detected_enemy_builds, flying_building_destinations)
            if self.position is not None:
                if self.unit_in_charge is None:
                    self.unit_in_charge = self.workers.get_builder(self.position)
                if self.unit_in_charge is not None:
                    unit_micro = MicroFactory.get_unit_micro(self.unit_in_charge)
                    await unit_micro.scout(self.unit_in_charge, self.position)
    
    attempted_expansion_positions = {}
    async def find_placement(self,
                            unit_type_id: UnitTypeId,
                            special_locations: SpecialLocations,
                            detected_enemy_builds: Dict[BuildType, float],
                            flying_building_destinations: Dict[int, Point2]) -> Point2 | None:
        new_build_position = None
        if unit_type_id == UnitTypeId.COMMANDCENTER:
            if BuildType.RUSH in detected_enemy_builds and self.bot.townhalls.amount < 2:
                candidates = [self.map.natural_position, self.map.natural_position, self.map.natural_position]
                start_terrain_height = self.bot.get_terrain_height(self.bot.start_location)
                vector = (self.bot.start_location - self.map.natural_position).normalized
                perpendicular_vector = Point2((-vector.y, vector.x))
                perpendicular_offsets = [0, 0.5, -0.5]
                candidate = candidates[0]
                offset_index = 0
                while self.bot.get_terrain_height(candidate) < start_terrain_height:
                    candidate = candidates[offset_index] + vector + perpendicular_vector * perpendicular_offsets[offset_index]
                    candidates[offset_index] = candidate
                    offset_index = (offset_index + 1) % 3
                # go a few more so it won't select a nearby low ground spot
                candidate = Point2(cy_towards(candidate, self.bot.start_location, distance=2))
                new_build_position = await self.bot.find_placement(
                    unit_type_id,
                    near=candidate,
                    max_distance=5,
                    placement_step=1,
                )
                if new_build_position is None:
                    LogHelper.add_log(f"Could not find CC placement near natural high ground at {candidate}, trying generic placement")
                    new_build_position = await self.find_generic_placement(unit_type_id, special_locations, flying_building_destinations)
            else:
                # modified from bot_ai get_next_expansion
                sorted_expansions = self.map.expansion_orders[ExpansionSelection.AWAY_FROM_ENEMY]
                available_expansions = []
                for location in sorted_expansions:
                    def is_near_to_expansion(t: Unit):
                        return cy_distance_to(t.position, location.expansion_position) < self.bot.EXPANSION_GAP_THRESHOLD

                    if any(map(is_near_to_expansion, self.bot.townhalls)):
                        # already taken
                        continue

                    # check that position hasn't already been attempted too many times
                    if location.expansion_position not in self.attempted_expansion_positions:
                        self.attempted_expansion_positions[location.expansion_position] = 0

                    available_expansions.append(location.expansion_position)

                if not available_expansions:
                    LogHelper.add_log("No valid expansions found. attempted_expansion_positions: {self.attempted_expansion_positions}")
                    self.attempted_expansion_positions.clear()
                    return None

                LogHelper.add_log(f"Expansions to check: {available_expansions}")
                used_expansion_count = len(self.bot.expansion_locations_list) - len(available_expansions)
                # skip past spots that are reserved for a cc that is out of position (flying)
                next_expansion_index = self.bot.townhalls.amount - used_expansion_count
                if next_expansion_index >= len(available_expansions):
                    # already have enough CCs for every base
                    return None
                new_build_position = available_expansions[next_expansion_index]

                if self.attempted_expansion_positions[new_build_position] > 3:
                    # build it wherever and fly it there later
                    LogHelper.add_log(f"Too many attempts to build cc at {new_build_position}, finding generic placement")
                    new_build_position = await self.find_generic_placement(unit_type_id, special_locations, flying_building_destinations)
                elif self.bot.game_info.map_name == 'Magannatha AIE':
                    # run it through find placement in case it's blocked by some weird map feature
                    new_build_position = await self.bot.find_placement(
                        unit_type_id,
                        near=new_build_position,
                        max_distance=4,
                        placement_step=2,
                    )

        elif unit_type_id == UnitTypeId.BUNKER:
            candidate: Point2
            if BuildType.RUSH in detected_enemy_builds and self.bot.structures.of_type(UnitTypeId.BARRACKS) \
                    and not self.bot.structures.of_type(UnitTypeId.BUNKER) \
                    and self.no_position_count == 0:
                # try to build near edge of high ground towards natural
                # high_ground_height = self.bot.get_terrain_height(self.bot.start_location)
                candidates = await SpecialLocations.get_bunker_positions(self.bot)
                # candidates = [(depot_position + ramp_barracks.position) / 2 for depot_position in self.bot.main_base_ramp.corner_depots]
                candidate = min(candidates, key=lambda p: cy_distance_to_squared(self.bot.start_location, p))
            elif self.bot.structures.of_type(UnitTypeId.BUNKER).amount < 2:
                ramp_position: Point2 = self.bot.main_base_ramp.bottom_center
                # enemy_start: Point2 = self.bot.enemy_start_locations[0]
                ramp_to_natural_vector = (self.map.natural_position - ramp_position).normalized
                ramp_to_natural_perp_vector = Point2((-ramp_to_natural_vector.x, ramp_to_natural_vector.y))
                toward_natural = ramp_position + ramp_to_natural_vector * 3
                candidates = [toward_natural + ramp_to_natural_perp_vector * 3, toward_natural - ramp_to_natural_perp_vector * 3]
                candidates.sort(key=lambda p: cy_distance_to_squared(p, self.bot.game_info.map_center))
                candidate = candidates[0]
            else:
                # find_placement only supports first 2 bunkers, 
                return None
            retry_count = 0
            while not new_build_position or cy_distance_to_squared(new_build_position, self.map.natural_position) < 16:
                if retry_count > 5:
                    new_build_position = None
                    break
                new_build_position = await self.bot.find_placement(
                                    unit_type_id,
                                    near=candidate,
                                    placement_step=retry_count + 1)
                retry_count += 1
        elif unit_type_id == UnitTypeId.MISSILETURRET:
            bases = self.bot.structures.of_type({UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS})
            turrets = self.bot.structures.of_type(UnitTypeId.MISSILETURRET)
            for base in bases:
                if not turrets or self.closest_distance_squared(base, turrets) > 100: # 10 squared
                    new_build_position = await self.bot.find_placement(
                        unit_type_id,
                        near=Point2(cy_towards(base.position, self.bot.game_info.map_center, distance=-4)),
                        placement_step=2,
                    )
                    break
        elif unit_type_id == UnitTypeId.SUPPLYDEPOT and self.bot.supply_cap < 45 and self.bot.enemy_race != Race.Terran:
            if BuildType.WORKER_RUSH in detected_enemy_builds and self.bot.structures.of_type(UnitTypeId.SUPPLYDEPOT).amount == 2:
                # try to build near edge of high ground towards natural
                new_build_position = self.bot.main_base_ramp.depot_in_middle
            elif not special_locations.is_blocked:
                new_build_position = special_locations.find_placement(unit_type_id)
            if new_build_position is None:
                new_build_position = await self.map.get_non_visible_position_in_main()
        elif unit_type_id == UnitTypeId.BARRACKS and BuildType.EARLY_EXPANSION in detected_enemy_builds and self.bot.structures(UnitTypeId.BARRACKS).amount < 2:
            new_build_position = self.map.enemy_expansion_orders[ExpansionSelection.AWAY_FROM_ENEMY][2].expansion_position
        else:
            new_build_position = await self.find_generic_placement(unit_type_id, special_locations, flying_building_destinations)

        if new_build_position:
            if self.bot.all_enemy_units:
                threats = self.bot.all_enemy_units.filter(lambda u: UnitTypes.can_attack_ground(u) and u.type_id not in UnitTypes.WORKER_TYPES)
                if threats and cy_closer_than(threats, 10, new_build_position):
                    logger.debug(f"found enemy near proposed build position {new_build_position}, rejecting")
                    return None
                
            if unit_type_id == UnitTypeId.COMMANDCENTER and BuildType.RUSH not in detected_enemy_builds:
                if new_build_position in self.attempted_expansion_positions:
                    self.attempted_expansion_positions[new_build_position] += 1
                else:
                    # build position isn't at the exact expansion location, may have been blocked
                    for build_pos in list(self.attempted_expansion_positions.keys()):
                        if cy_distance_to(new_build_position, build_pos) < 10:
                            self.attempted_expansion_positions[build_pos] += 1
                            break
        return new_build_position
    
    async def find_generic_placement(self, unit_type_id: UnitTypeId, special_locations: SpecialLocations, flying_building_destinations: Dict[int, Point2]) -> Point2 | None:
        logger.debug(f"finding placement for {unit_type_id}")
        new_build_position: Point2 | None = None
        if unit_type_id == UnitTypeId.REFINERYRICH:
            unit_type_id = UnitTypeId.REFINERY
        if not special_locations.is_blocked:
            new_build_position = special_locations.find_placement(unit_type_id)
        addon_place = unit_type_id in (
            UnitTypeId.BARRACKS,
            UnitTypeId.FACTORY,
            UnitTypeId.STARPORT,
        )
        prefer_earlier_bases = unit_type_id in (
            UnitTypeId.SUPPLYDEPOT,
            UnitTypeId.BARRACKS,
            UnitTypeId.FACTORY,
            UnitTypeId.STARPORT,
            UnitTypeId.ENGINEERINGBAY,
            UnitTypeId.GHOSTACADEMY,
            UnitTypeId.FUSIONCORE,
            UnitTypeId.ARMORY,
        )
        go_away_from_map_center = unit_type_id in UnitTypes.TECH_STRUCTURE_TYPES
        distance_towards_map_center = -8 if go_away_from_map_center else 8
        map_center = self.bot.game_info.map_center
        max_distance = 20
        retry_count = 0
        while new_build_position is None:
            try:
                if self.bot.townhalls:
                    preferred_townhalls = self.bot.townhalls
                    if prefer_earlier_bases and retry_count < 2:
                        ready_townhalls = self.bot.townhalls.ready
                        if len(ready_townhalls) == 1:
                            preferred_townhalls = ready_townhalls
                        elif ready_townhalls:
                            non_flying_townhalls = ready_townhalls.filter(lambda th: not th.is_flying)
                            if len(non_flying_townhalls) == 1:
                                preferred_townhalls = non_flying_townhalls
                            elif non_flying_townhalls:
                                closest_townhall_to_enemy: Unit = self.map.get_closest_unit_by_path(non_flying_townhalls, self.bot.enemy_start_locations[0])
                                preferred_townhalls = non_flying_townhalls.filter(lambda th: th.tag != closest_townhall_to_enemy.tag)
                            else:
                                preferred_townhalls = ready_townhalls
                    for townhall in preferred_townhalls:
                        new_build_position = await self.bot.find_placement(
                            unit_type_id,
                            near=townhall.position.towards_with_random_angle(map_center, distance=distance_towards_map_center, max_difference=1.6),
                            placement_step=2,
                            addon_place=addon_place,
                            max_distance=max_distance,
                        )
                        if new_build_position is not None:
                            break
                else:
                    new_build_position = await self.bot.find_placement(
                        unit_type_id,
                        near=self.bot.start_location,
                        placement_step=2,
                        addon_place=addon_place,
                        max_distance=max_distance,
                    )
            except (ConnectionAlreadyClosedError, ConnectionResetError, ProtocolError):
                return None
            if new_build_position:
                # don't build near edge to avoid trapping units
                edge_distance = self.map.get_distance_from_edge(new_build_position.rounded)
                if edge_distance <= 3:
                    # accept defeat, is ok to do it sometimes
                    new_build_position = None
            if new_build_position:
                for tag, destination in flying_building_destinations.items():
                    flying_building = self.bot.structures.find_by_tag(tag)
                    if not flying_building:
                        continue
                    if min(abs(new_build_position.x - destination.x), abs(new_build_position.y - destination.y)) < BUILDING_RADIUS[flying_building.type_id]:
                        new_build_position = None
                        break
            if new_build_position is None:
                max_distance += 1
                retry_count += 1
                if retry_count > 25:
                    # give up
                    break
        return new_build_position

    def get_geysir(self) -> Unit | None:
        if self.bot.townhalls:
            vespene_geysirs = Units([], self.bot)
            if self.bot.townhalls.ready:
                vespene_geysirs = self.bot.vespene_geyser.in_distance_of_group(
                    distance=10, other_units=self.bot.townhalls.ready
                )
            if len(self.bot.gas_buildings) == len(vespene_geysirs):
                # no empty near ready townhalls, include in-progress townhalls
                vespene_geysirs = self.bot.vespene_geyser.in_distance_of_group(
                    distance=10, other_units=self.bot.townhalls
                )
            if len(self.bot.gas_buildings) == len(vespene_geysirs):
                return None
            if self.bot.gas_buildings and vespene_geysirs:
                vespene_geysirs = vespene_geysirs.filter(
                    lambda geysir: self.bot.gas_buildings.closest_distance_to(geysir) > 1)
            if vespene_geysirs:
                return cy_closest_to(self.bot.start_location, vespene_geysirs)
        return None

    unit_types_to_finish_despite_enemies = {
        UnitTypeId.BUNKER,
        UnitTypeId.COMMANDCENTER,
        UnitTypeId.ORBITALCOMMAND,
        UnitTypeId.PLANETARYFORTRESS,
        UnitTypeId.BARRACKS,
        UnitTypeId.FACTORY,
        UnitTypeId.STARPORT,
    }
    @timed_async
    async def is_interrupted(self) -> bool:
        interrupted = False
        if self.unit_in_charge is None or self.position is None:
            interrupted = True
            LogHelper.add_log(f"{self} interrupted due to no worker {self.unit_in_charge} or position {self.position}")
        else:
            if self.start_time == 0.0 or self.bot.time - self.start_time < 0.5:
                return False
            self.check_idle: bool = (
                self.check_idle
                or (
                    self.unit_in_charge.is_active and not self.unit_in_charge.is_gathering
                )
            )
            if not self.check_idle:
                return False
            flee_enemies = True
            if self.unit_type_id in self.unit_types_to_finish_despite_enemies and self.unit_being_built and self.unit_being_built.build_progress > 0.6:
                flee_enemies = False
            if flee_enemies:
                micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.unit_in_charge)
                if await micro._retreat(self.unit_in_charge, 0.8) == UnitMicroType.RETREAT:
                    interrupted = True
                    LogHelper.add_log(f"{self} interrupted due to retreating worker {self.unit_in_charge}")

            if not interrupted and not self.unit_in_charge.is_constructing_scv:
                if self.unit_being_built:
                    self.unit_in_charge.smart(self.unit_being_built)
                else:
                    if self.unit_type_id == UnitTypeId.REFINERY and self.geysir:
                        if self.bot.gas_buildings and self.bot.gas_buildings.closest_distance_to(self.geysir) > 1:
                            self.unit_in_charge(
                                self.bot.game_data.units[self.unit_type_id.value].creation_ability.id, # type: ignore
                                target=self.geysir,
                                queue=False,
                                subtract_cost=False,
                                can_afford_check=False,
                            )
                        else:
                            interrupted = True
                            LogHelper.add_log(f"{self} interrupted due to unit not constructing")
                    else:
                        # position might not be buildable, can't trust can_place_single
                        interrupted = True
                        LogHelper.add_log(f"{self} interrupted due to unit not constructing")
            if not interrupted:
                if self.unit_being_built is None:
                    if self.unit_in_charge.is_constructing_scv:
                        order_position = self.unit_in_charge.orders[0].target
                        if isinstance(order_position, Point2):
                            if order_position == self.position:
                                in_progress_structures = self.bot.structures.filter(lambda s: not s.is_ready)
                                if in_progress_structures:
                                    construction = cy_closer_than(in_progress_structures, 1, order_position)
                                    if construction and construction[0].type_id == self.unit_type_id:
                                        self.unit_being_built = construction[0]
                                        self.position = construction[0].position
                                        return False
                    if cy_distance_to_squared(self.unit_in_charge.position, self.position) < 9 and \
                            self.worker_in_position_time is None and self.bot.can_afford(self.unit_type_id):
                        self.worker_in_position_time = self.bot.time
                    elif self.worker_in_position_time is not None and self.bot.time - self.worker_in_position_time > 5 and \
                            self.cost.minerals <= self.bot.minerals and self.cost.vespene <= self.bot.vespene:
                        # position may be blocked
                        interrupted = True
                        LogHelper.add_log(f"{self} interrupted due to unit waiting too long")
                elif self.unit_in_charge.is_idle:
                    self.unit_in_charge.smart(self.unit_being_built)
            if not interrupted and flee_enemies:
                # check for interruption due to nearby enemies
                if cy_distance_to(self.position, self.bot.start_location) < 15:
                    # don't interrupt builds in main base
                    return False
                threats = self.bot.all_enemy_units.filter(
                    lambda u: UnitTypes.can_attack_ground(u) \
                        and u.type_id not in UnitTypes.WORKER_TYPES)
                if threats:
                    enemy_is_close = self.unit_is_closer_than(self.unit_in_charge, threats, 12)
                    if not enemy_is_close:
                        return False
                    if self.unit_in_charge:
                        interrupted = True
                        LogHelper.add_log(f"{self} interrupted due threats")

        if interrupted:
            self.set_interrupted()
        return interrupted
    
    def set_interrupted(self):
        if self.unit_type_id != UnitTypeId.BUNKER:
            self.position = None
        self.geysir = None
        self.worker_in_position_time = None
        if self.unit_in_charge:
            self.workers.set_as_idle(self.unit_in_charge)
        self.unit_in_charge = None
        self.start_time = 0.0

    def cancel_construction(self):
        logger.debug(f"canceling build of {self.unit_being_built}")
        if self.unit_being_built:
            if self.unit_being_built.age != 0:
                self.unit_being_built = UnitReferenceHelper.get_updated_unit_reference(self.unit_being_built)
            self.unit_being_built(AbilityId.CANCEL_BUILDINPROGRESS)
        self.last_cancel_time = self.bot.time
        self.unit_being_built = None
        if self.unit_in_charge and self.unit_in_charge.type_id == UnitTypeId.SCV:
            self.workers.update_assigment(self.unit_in_charge, WorkerJobType.IDLE, None)
            self.unit_in_charge = None
        self.position = None
        self.geysir = None
        self.worker_in_position_time = None
        self.is_in_progress = False
        self.check_idle = False
        self.start_time = 0.0
        self.completed_time = None
