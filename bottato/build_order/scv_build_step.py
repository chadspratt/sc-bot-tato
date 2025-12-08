from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit_command import UnitCommand
from sc2.position import Point2
from sc2.protocol import ConnectionAlreadyClosedError, ProtocolError

from bottato.log_helper import LogHelper
from bottato.enums import BuildResponseCode, RushType, WorkerJobType
from bottato.unit_types import UnitTypes
from bottato.map.map import Map
from bottato.economy.workers import Workers
from bottato.economy.production import Production
from bottato.build_order.build_step import BuildStep
from bottato.build_order.special_locations import SpecialLocations
from bottato.tech_tree import TECH_TREE
from bottato.micro.micro_factory import MicroFactory
from bottato.micro.base_unit_micro import BaseUnitMicro

class SCVBuildStep(BuildStep):
    unit_type_id: UnitTypeId
    position: Point2 | None = None
    unit_being_built: Unit | None = None
    position: Point2 | None = None
    geysir: Unit | None = None
    worker_in_position_time: float | None = None

    def __init__(self, unit_type_id: UnitTypeId, bot: BotAI, workers: Workers, production: Production, map: Map):
        super().__init__(unit_type_id, bot, workers, production, map)
        self.unit_type_id = unit_type_id

    def __repr__(self) -> str:
        builder = self.unit_in_charge if self.unit_in_charge else self.builder_type
        target = ""
        if self.unit_being_built:
            target = f"{self.unit_being_built} {self.unit_being_built.build_progress}"
        else:
            target = self.unit_type_id.name

        return f"{target}-built by {builder}"

    def update_references(self, units_by_tag: dict[int, Unit]):
        logger.debug(f"unit in charge: {self.unit_in_charge}")
        if self.unit_in_charge:
            try:
                self.unit_in_charge = self.get_updated_unit_reference(self.unit_in_charge, self.bot, units_by_tag)
            except self.UnitNotFound:
                self.unit_in_charge = None
        if self.geysir:
            try:
                self.geysir = self.get_updated_unit_reference(self.geysir, self.bot, units_by_tag)
            except self.UnitNotFound:
                self.geysir = None
        if self.unit_being_built:
            try:
                self.unit_being_built = self.get_updated_unit_reference(self.unit_being_built, self.bot, units_by_tag)
            except self.UnitNotFound:
                self.unit_being_built = None

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
        return self.unit_type_id == unit_type_id or \
            self.unit_type_id == UnitTypeId.REFINERY and unit_type_id == UnitTypeId.REFINERYRICH

    def get_unit_type_id(self) -> UnitTypeId | None:
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

    async def execute(self, special_locations: SpecialLocations, rush_detected_type: RushType) -> BuildResponseCode:
        self.start_timer("scv_build_step.execute inner")

        self.start_timer(f"scv_build_step.execute_scv_build {self.unit_type_id}")
        response = await self.execute_scv_build(special_locations, rush_detected_type)
        self.stop_timer(f"scv_build_step.execute_scv_build {self.unit_type_id}")
            
        if response == BuildResponseCode.SUCCESS:
            self.is_in_progress = True
        self.stop_timer("scv_build_step.execute inner")
        return response
    
    async def execute_scv_build(self, special_locations: SpecialLocations, rush_detected_type: RushType) -> BuildResponseCode:
        if self.unit_type_id in TECH_TREE:
            # check that all tech requirements are met
            for requirement in TECH_TREE[self.unit_type_id]:
                if self.bot.structure_type_build_progress(requirement) != 1:
                    return BuildResponseCode.NO_TECH

        if self.unit_being_built:
            self.position = self.unit_being_built.position
            if self.start_time is None:
                self.start_time = self.bot.time
        else:
            if self.unit_type_id == UnitTypeId.REFINERY:
                # Vespene targets unit to build instead of position
                self.geysir: Unit | None = self.get_geysir()
                if self.geysir is None:
                    return BuildResponseCode.NO_FACILITY
                self.position = self.geysir.position
            else:
                if self.position is None or (self.start_time is not None and self.start_time - self.bot.time > 5):
                    self.position = await self.find_placement(self.unit_type_id, special_locations, rush_detected_type)
                if self.position is None:
                    return BuildResponseCode.NO_LOCATION

        threats = None
        if self.bot.enemy_units:
            threats = self.bot.enemy_units.filter(lambda u: UnitTypes.can_attack_ground(u))
        if threats and threats.closest_distance_to(self.position) < 15:
            return BuildResponseCode.TOO_CLOSE_TO_ENEMY

        if self.unit_in_charge is None:
            self.unit_in_charge = self.workers.get_builder(self.position)
        if self.unit_in_charge is None:
            return BuildResponseCode.NO_BUILDER

        build_response: bool | UnitCommand
        if self.unit_being_built:
            build_response = self.unit_in_charge.smart(self.unit_being_built)
        else:
            if self.unit_type_id == UnitTypeId.REFINERY and self.geysir:
                build_response = self.unit_in_charge.build_gas(self.geysir)
            else:
                # self.unit_in_charge.move(self.position)
                build_response = self.unit_in_charge.build(
                    self.unit_type_id, self.position
                )

        return BuildResponseCode.SUCCESS if build_response else BuildResponseCode.FAILED

    async def position_worker(self, special_locations: SpecialLocations, rush_detected_type: RushType):
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
                    self.position = await self.find_placement(self.unit_type_id, special_locations, rush_detected_type)
            if self.position is not None:
                if self.unit_in_charge is None:
                    self.unit_in_charge = self.workers.get_builder(self.position)
                if self.unit_in_charge is not None:
                    self.unit_in_charge.move(self.position)
    
    attempted_expansion_positions = {}
    async def find_placement(self, unit_type_id: UnitTypeId, special_locations: SpecialLocations, rush_detected_type: RushType) -> Point2 | None:
        new_build_position = None
        if unit_type_id == UnitTypeId.COMMANDCENTER and (rush_detected_type == RushType.NONE or self.bot.townhalls.amount >= 2):
            # modified from bot_ai get_next_expansion
            expansions_to_check = []
            for el in self.bot.expansion_locations_list:
                def is_near_to_expansion(t):
                    return t.distance_to(el) < self.bot.EXPANSION_GAP_THRESHOLD

                if any(map(is_near_to_expansion, self.bot.townhalls)):
                    # already taken
                    continue
                
                # check that position hasn't already been attempted too many times
                if el not in self.attempted_expansion_positions:
                    self.attempted_expansion_positions[el] = 0
                elif self.attempted_expansion_positions[el] > 3:
                    LogHelper.add_log(f"Skipping expansion at {el}, attempted too many times")
                    continue

                expansions_to_check.append(el)

            if not expansions_to_check:
                LogHelper.add_log("No valid expansions found. attempted_expansion_positions: {self.attempted_expansion_positions}")
                self.attempted_expansion_positions.clear()
                return None

            LogHelper.add_log(f"Expansions to check: {expansions_to_check}")
            new_build_position = self.map.get_closest_position_by_path(expansions_to_check, self.bot.start_location)

            # run it through find placement in case it's blocked by some weird map feature
            if self.bot.game_info.map_name == 'Magannatha AIE':
                new_build_position = await self.bot.find_placement(
                    unit_type_id,
                    near=new_build_position,
                    max_distance=4,
                    placement_step=2,
                )

        elif unit_type_id == UnitTypeId.BUNKER:
            candidate: Point2
            if rush_detected_type != RushType.NONE and self.bot.structures.of_type(UnitTypeId.BARRACKS) and not self.bot.structures.of_type(UnitTypeId.BUNKER):
                # try to build near edge of high ground towards natural
                # high_ground_height = self.bot.get_terrain_height(self.bot.start_location)
                ramp_barracks = self.bot.structures.of_type(UnitTypeId.BARRACKS).closest_to(self.bot.main_base_ramp.barracks_correct_placement) # type: ignore
                candidates = [(depot_position + ramp_barracks.position) / 2 for depot_position in self.bot.main_base_ramp.corner_depots]
                candidate = max(candidates, key=lambda p: ramp_barracks.add_on_position.distance_to(p))
                candidate = candidate.towards(self.bot.main_base_ramp.top_center.towards(ramp_barracks.position, distance=2), distance=-1) # type: ignore
            else:
                ramp_position: Point2 = self.bot.main_base_ramp.bottom_center
                # enemy_start: Point2 = self.bot.enemy_start_locations[0]
                ramp_to_natural_vector = (self.map.natural_position - ramp_position).normalized
                ramp_to_natural_perp_vector = Point2((-ramp_to_natural_vector.x, ramp_to_natural_vector.y))
                toward_natural = ramp_position + ramp_to_natural_vector * 3
                candidates = [toward_natural + ramp_to_natural_perp_vector * 3, toward_natural - ramp_to_natural_perp_vector * 3]
                candidates.sort(key=lambda p: p.distance_to(self.bot.game_info.map_center))
                candidate = candidates[0]
                # candidate = ramp_position.towards(self.map.natural_position, 2).towards(enemy_start, distance=1)
            retry_count = 0
            while not new_build_position or self.bot.distance_math_hypot_squared(new_build_position, self.map.natural_position) < 16:
                new_build_position = await self.bot.find_placement(
                                    unit_type_id,
                                    near=candidate,
                                    placement_step=1)
                retry_count += 1
                if retry_count > 5:
                    break
        elif unit_type_id == UnitTypeId.MISSILETURRET:
            bases = self.bot.structures.of_type({UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS})
            turrets = self.bot.structures.of_type(UnitTypeId.MISSILETURRET)
            for base in bases:
                if not turrets or self.closest_distance_squared(base, turrets) > 100: # 10 squared
                    new_build_position = await self.bot.find_placement(
                        unit_type_id,
                        near=base.position.towards(self.bot.game_info.map_center, distance=-4), # type: ignore
                        placement_step=2,
                    )
                    break
        elif unit_type_id == UnitTypeId.SUPPLYDEPOT and self.bot.supply_cap < 45:
            if not special_locations.is_blocked:
                new_build_position = special_locations.find_placement(unit_type_id)
            if new_build_position is None:
                new_build_position = await self.map.get_non_visible_position_in_main()
        else:
            logger.debug(f"finding placement for {unit_type_id}")
            if not special_locations.is_blocked:
                new_build_position = special_locations.find_placement(unit_type_id)
            if new_build_position is None:
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
                map_center = self.bot.game_info.map_center
                max_distance = 20
                retry_count = 0
                while new_build_position is None:
                    try:
                        if self.bot.townhalls:
                            preferred_townhalls = self.bot.townhalls
                            if prefer_earlier_bases and retry_count == 0:
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
                                    near=townhall.position.towards_with_random_angle(map_center, distance=8, max_difference=1.6),
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
                            max_distance += 1
                            logger.debug(f"{new_build_position} is {edge_distance} from edge")
                            # accept defeat, is ok to do it sometimes
                            if max_distance > 25:
                                break
                            retry_count += 1
                            new_build_position = None
        if new_build_position:
            if self.bot.all_enemy_units:
                threats = self.bot.all_enemy_units.filter(lambda u: UnitTypes.can_attack_ground(u) and u.type_id not in (UnitTypeId.DRONE, UnitTypeId.SCV, UnitTypeId.PROBE))
                if threats and threats.closer_than(10, new_build_position):
                    logger.debug(f"found enemy near proposed build position {new_build_position}, rejecting")
                    return None
                
            if unit_type_id == UnitTypeId.COMMANDCENTER and rush_detected_type == RushType.NONE:
                if new_build_position in self.attempted_expansion_positions:
                    self.attempted_expansion_positions[new_build_position] += 1
                else:
                    # build position isn't at the exact expansion location, may have been blocked
                    for build_pos in list(self.attempted_expansion_positions.keys()):
                        if new_build_position.distance_to(build_pos) < 10:
                            self.attempted_expansion_positions[build_pos] += 1
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
                return vespene_geysirs.closest_to(self.bot.start_location)
        return None

    async def is_interrupted(self) -> bool:
        interrupted = False
        if self.unit_in_charge is None or self.position is None:
            interrupted = True
        else:
            self.check_idle: bool = (
                self.check_idle
                or (
                    self.unit_in_charge.is_active and not self.unit_in_charge.is_gathering
                )
            )
            if not self.check_idle:
                return False
            
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.unit_in_charge)
            if await micro._retreat(self.unit_in_charge, 0.8):
                interrupted = True

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
                    else:
                        # position might not be buildable, can't trust can_place_single
                        interrupted = True
            if not interrupted:
                if self.unit_being_built is None:
                    if self.unit_in_charge.distance_to_squared(self.position) < 9 and \
                            self.worker_in_position_time is None and self.bot.can_afford(self.unit_type_id):
                        self.worker_in_position_time = self.bot.time
                    elif self.worker_in_position_time is not None and self.bot.time - self.worker_in_position_time > 5 and \
                            self.cost.minerals <= self.bot.minerals and self.cost.vespene <= self.bot.vespene:
                        # position may be blocked
                        interrupted = True
                elif self.unit_in_charge.is_idle:
                    self.unit_in_charge.smart(self.unit_being_built)
            if not interrupted:
                # check for interruption due to nearby enemies
                if self.position.distance_to(self.bot.start_location) < 15:
                    # don't interrupt builds in main base
                    return False
                threats = self.bot.enemy_units.filter(
                    lambda u: UnitTypes.can_attack_ground(u) \
                        and u.type_id not in (UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE))
                if threats:
                    closest_threat = threats.closest_to(self.unit_in_charge)
                    enemy_is_close = closest_threat.distance_to_squared(self.unit_in_charge) < 144 # 12 squared
                    if not enemy_is_close:
                        return False
                    if self.unit_in_charge:
                        self.unit_in_charge(AbilityId.HALT)
                        interrupted = True

        if interrupted:
            self.is_in_progress = False
            self.position = None
            self.geysir = None
            self.worker_in_position_time = None
            if self.unit_in_charge:
                self.workers.set_as_idle(self.unit_in_charge)
            self.unit_in_charge = None
        return interrupted

    def cancel_construction(self):
        logger.debug(f"canceling build of {self.unit_being_built}")
        if self.unit_being_built:
            if self.unit_being_built.age != 0:
                self.unit_being_built = self.get_updated_unit_reference(self.unit_being_built, self.bot, None)
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
        self.start_time = None
        self.completed_time = None
