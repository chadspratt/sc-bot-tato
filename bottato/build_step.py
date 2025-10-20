import enum
import math
from loguru import logger
from typing import Optional, Union

from sc2.dicts.unit_research_abilities import RESEARCH_INFO
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2, Point3
from sc2.dicts.unit_train_build_abilities import TRAIN_INFO
from sc2.protocol import ConnectionAlreadyClosedError, ProtocolError

from bottato.map.map import Map
from bottato.mixins import UnitReferenceMixin, GeometryMixin, TimerMixin
from bottato.economy.workers import JobType, Workers
from bottato.economy.production import Production
from bottato.special_locations import SpecialLocations
from bottato.upgrades import RESEARCH_ABILITIES
from bottato.map.destructibles import BUILDING_RADIUS
from bottato.tech_tree import TECH_TREE


class ResponseCode(enum.Enum):
    SUCCESS = 0
    FAILED = 1
    NO_BUILDER = 2
    NO_FACILITY = 3
    NO_TECH = 4
    NO_LOCATION = 5
    NO_RESOURCES = 6
    NO_SUPPLY = 7
    QUEUE_EMPTY = 8
    TOO_CLOSE_TO_ENEMY = 9


class BuildStep(UnitReferenceMixin, GeometryMixin, TimerMixin):
    unit_type_id: UnitTypeId = None
    upgrade_id: UpgradeId = None
    unit_in_charge: Optional[Unit] = None
    unit_being_built: Optional[Unit] = None
    position: Union[Unit, Point2] = None
    geysir: Unit = None
    check_idle: bool = False
    last_cancel_time: float = -10
    start_time: int = None
    completed_time: int = None
    worker_in_position_time: int = None
    is_in_progress: bool = False

    def __init__(self, unit_type: Union[UnitTypeId, UpgradeId], bot: BotAI, workers: Workers, production: Production, map: Map):
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.production: Production = production
        self.map: Map = map

        if isinstance(unit_type, UnitTypeId):
            self.unit_type_id = unit_type
        else:
            self.upgrade_id = unit_type
        self.friendly_name = unit_type.name
        self.builder_type: UnitTypeId = self.production.get_builder_type(unit_type)
        self.cost = bot.calculate_cost(unit_type)
        self.supply_cost = bot.calculate_supply_cost(unit_type)

    def __repr__(self) -> str:
        builder = self.unit_in_charge if self.unit_in_charge else self.builder_type
        # orders = self.unit_in_charge.orders if self.unit_in_charge else '[]'
        target = ""
        if self.unit_being_built and self.unit_being_built is not True:
            target = f"{self.unit_being_built} {self.unit_being_built.build_progress}"
        elif self.unit_type_id:
            target = self.unit_type_id.name
        elif self.upgrade_id:
            target = self.upgrade_id.name

        return f"{target}-built by {builder}"

    @property
    def is_unit(self) -> bool:
        return self.builder_type in {UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}

    def draw_debug_box(self):
        if self.unit_in_charge is not None:
            self.bot.client.debug_sphere_out(self.unit_in_charge, 1, (255, 130, 0))
            if self.position:
                self.bot.client.debug_line_out(self.unit_in_charge, self.convert_point2_to_3(self.position), (255, 130, 0))
            if self.unit_type_id:
                self.bot.client.debug_text_world(
                    self.unit_type_id.name, self.unit_in_charge.position3d)
            elif self.upgrade_id:
                self.bot.client.debug_text_world(
                    self.upgrade_id.name, self.unit_in_charge.position3d)
        if self.position:
            self.bot.client.debug_box2_out(self.convert_point2_to_3(self.position), 0.5)
            self.bot.client.debug_text_world(
                self.unit_type_id.name, Point3((*self.position, 10))
            )
        if self.unit_being_built is not None and self.unit_being_built is not True:
            logger.debug(f"unit being built {self.unit_being_built}")
            self.bot.client.debug_box2_out(self.unit_being_built, 0.75)

    def update_references(self, units_by_tag: dict[int, Unit]):
        logger.debug(f"unit in charge: {self.unit_in_charge}")
        try:
            self.unit_in_charge = self.get_updated_unit_reference(self.unit_in_charge, units_by_tag)
        except self.UnitNotFound:
            self.unit_in_charge = None
        if isinstance(self.unit_being_built, Unit):
            try:
                self.unit_being_built = self.get_updated_unit_reference(self.unit_being_built, units_by_tag)
            except self.UnitNotFound:
                self.unit_being_built = None

    async def execute(self, special_locations: SpecialLocations, rush_defense_enacted: bool = False) -> ResponseCode:
        self.start_timer("build_step.execute inner")
        response = None
        if self.upgrade_id:
            self.start_timer(f"build_step.execute_upgrade {self.upgrade_id}")
            response = self.execute_upgrade()
            self.stop_timer(f"build_step.execute_upgrade {self.upgrade_id}")
        elif UnitTypeId.SCV in self.builder_type:
            self.start_timer(f"build_step.execute_scv_build {self.unit_type_id}")
            response = await self.execute_scv_build(special_locations, rush_defense_enacted)
            self.stop_timer(f"build_step.execute_scv_build {self.unit_type_id}")
        else:
            self.start_timer(f"build_step.execute_facility_build {self.unit_type_id}")
            response = self.execute_facility_build()
            self.stop_timer(f"build_step.execute_facility_build {self.unit_type_id}")
        if response == ResponseCode.SUCCESS:
            self.is_in_progress = True
        self.stop_timer("build_step.execute inner")
        return response

    def execute_upgrade(self) -> ResponseCode:
        response = None
        logger.debug(f"researching upgrade {self.upgrade_id}")
        if self.unit_in_charge is None:
            self.unit_in_charge = self.production.get_research_facility(self.upgrade_id)
            logger.debug(f"research facility: {self.unit_in_charge}")
        if self.unit_in_charge is None or self.unit_in_charge.type_id == UnitTypeId.TECHLAB:
            response = ResponseCode.NO_FACILITY
        else:
            # successful_action: bool = self.unit_in_charge.research(self.upgrade_id)
            ability = RESEARCH_ABILITIES[self.upgrade_id]

            required_tech_building: UnitTypeId | None = RESEARCH_INFO[self.unit_in_charge.type_id][self.upgrade_id].get(
                "required_building", None
            )
            requirement_met = (
                required_tech_building is None or self.bot.structure_type_build_progress(required_tech_building) == 1
            )
            if not requirement_met:
                return ResponseCode.NO_TECH
            logger.debug(f"{self.unit_in_charge} researching upgrade with ability {ability}")
            successful_action: bool = self.unit_in_charge(ability)
            if successful_action:
                response = ResponseCode.SUCCESS
        if response is None:
            logger.debug("upgrade failed to start")
            response = ResponseCode.FAILED

        return response

    async def execute_scv_build(self, special_locations: SpecialLocations, rush_detected: bool = False) -> ResponseCode:
        response = None
        logger.debug(f"Trying to build {self.unit_type_id} with SCV")

        if self.unit_type_id in TECH_TREE:
            # check that all tech requirements are met
            for requirement in TECH_TREE[self.unit_type_id]:
                if self.bot.structure_type_build_progress(requirement) != 1:
                    return ResponseCode.NO_TECH

        build_response: bool = None
        if self.unit_type_id == UnitTypeId.REFINERY:
            # Vespene targets unit to build instead of position
            self.geysir: Union[Unit, None] = self.get_geysir()
            if self.geysir is None:
                response = ResponseCode.NO_FACILITY
            else:
                self.position = self.geysir.position
                threats = None
                if self.bot.enemy_units:
                    threats = self.bot.enemy_units.filter(lambda u: u.can_attack_ground)
                if threats and threats.closest_distance_to(self.position) < 15:
                    logger.debug(f"{self} Too close to enemy!")
                    response = ResponseCode.TOO_CLOSE_TO_ENEMY
                else:
                    if self.unit_in_charge is None:
                        self.unit_in_charge = self.workers.get_builder(self.position)
                    if self.unit_in_charge is None:
                        response = ResponseCode.NO_BUILDER
                    else:
                        build_response = self.unit_in_charge.build_gas(self.geysir)
        else:
            if self.position is None or (self.unit_being_built is None and self.start_time is not None and self.start_time - self.bot.time > 5):
                self.position = await self.find_placement(self.unit_type_id, special_locations, rush_detected)
            if self.position is None:
                response = ResponseCode.NO_LOCATION
            else:
                threats = None
                if self.bot.enemy_units:
                    threats = self.bot.enemy_units.filter(lambda u: u.can_attack_ground)
                if threats and threats.closest_distance_to(self.position) < 15:
                    logger.debug(f"{self} Too close to enemy!")
                    response = ResponseCode.TOO_CLOSE_TO_ENEMY
                else:
                    if self.unit_in_charge is None:
                        self.unit_in_charge = self.workers.get_builder(self.position)
                    if self.unit_in_charge is None:
                        response = ResponseCode.NO_BUILDER
                    else:
                        logger.debug(
                            f"Trying to build structure {self.unit_type_id} at {self.position}"
                        )
                        self.unit_in_charge.move(self.position)

                        if self.unit_being_built is None:
                            build_response = self.unit_in_charge.build(
                                self.unit_type_id, self.position
                            )
                        else:
                            self.start_time = self.bot.time
                            build_response = self.unit_in_charge.smart(self.unit_being_built)
                            logger.debug(f"{self.unit_in_charge} in charge is doing {self.unit_in_charge.orders}")
        if build_response is not None:
            response = ResponseCode.SUCCESS if build_response else ResponseCode.FAILED

        return response
    
    async def position_worker(self, special_locations: SpecialLocations, rush_detected: bool = False):
        if UnitTypeId.SCV in self.builder_type:
            if self.position is None:
                if self.unit_type_id == UnitTypeId.REFINERY:
                    # Vespene targets unit to build instead of position
                    self.geysir: Union[Unit, None] = self.get_geysir()
                    if self.geysir is None:
                        return
                    self.position = self.geysir.position
                else:
                    self.position = await self.find_placement(self.unit_type_id, special_locations, rush_detected=rush_detected)
            if self.position is not None:
                if self.unit_in_charge is None:
                    self.unit_in_charge = self.workers.get_builder(self.position)
                if self.unit_in_charge is not None:
                    self.unit_in_charge.move(self.position)

    def execute_facility_build(self) -> ResponseCode:
        response = None
        # not built by scv
        logger.debug(
            f"Trying to train unit {self.unit_type_id} with {self.builder_type}"
        )

        if self.unit_type_id in TECH_TREE:
            # check that all tech requirements are met
            for requirement in TECH_TREE[self.unit_type_id]:
                if self.bot.structure_type_build_progress(requirement) != 1:
                    return ResponseCode.NO_TECH
        if self.builder_type.intersection({UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT}):
            self.unit_in_charge = self.production.get_builder(self.unit_type_id)
            if self.unit_in_charge and self.unit_type_id in self.production.add_on_types:
                self.position = self.unit_in_charge.add_on_position
        elif self.unit_type_id == UnitTypeId.SCV:
            # scv
            facility_candidates = self.bot.townhalls.filter(lambda x: x.is_ready and x.is_idle and not x.is_flying)
            facility_candidates.sort(key=lambda x: x.type_id == UnitTypeId.COMMANDCENTER)
            self.unit_in_charge = facility_candidates[0] if facility_candidates else None
        else:
            facility_candidates = self.bot.structures.filter(lambda x: x.type_id in self.builder_type and x.is_ready and x.is_idle and not x.is_flying)
            self.unit_in_charge = facility_candidates[0] if facility_candidates else None

        if self.unit_in_charge is None:
            logger.debug("no idle training facility")
            response = ResponseCode.NO_FACILITY
        else:
            if self.unit_type_id in {UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS}:
                self.unit_being_built = self.unit_in_charge
            else:
                self.unit_being_built = True
            # self.pos = self.unit_in_charge.position
            logger.debug(f"Found training facility {self.unit_in_charge}")
            build_response = self.unit_in_charge(self.get_build_ability())
            response = ResponseCode.SUCCESS if build_response else ResponseCode.FAILED
        return response

    def get_build_ability(self) -> AbilityId:
        if self.unit_type_id in {
            UnitTypeId.BARRACKSREACTOR,
            UnitTypeId.FACTORYREACTOR,
            UnitTypeId.STARPORTREACTOR,
        }:
            return AbilityId.BUILD_REACTOR
        if self.unit_type_id in {
            UnitTypeId.BARRACKSTECHLAB,
            UnitTypeId.FACTORYTECHLAB,
            UnitTypeId.STARPORTTECHLAB,
        }:
            return AbilityId.BUILD_TECHLAB
        return TRAIN_INFO[self.unit_in_charge.type_id][self.unit_type_id]["ability"]

    attempted_expansion_positions = {}
    async def find_placement(self, unit_type_id: UnitTypeId, special_locations: SpecialLocations, rush_detected: bool = False) -> Union[Point2, None]:
        new_build_position = None
        if unit_type_id == UnitTypeId.COMMANDCENTER and (not rush_detected or self.bot.townhalls.amount >= 2):
            # modified from bot_ai get_next_expansion
            shortest_distance = math.inf
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
                    continue

                expansions_to_check.append(el)

            if not expansions_to_check:
                logger.info("No valid expansions found. attempted_expansion_positions: {self.attempted_expansion_positions}")
                self.attempted_expansion_positions.clear()
                return None

            paths_to_check = [[self.bot.game_info.player_start_location, expansion] for expansion in expansions_to_check]
            distances = await self.bot.client.query_pathings(paths_to_check)
            
            for path, distance in zip(paths_to_check, distances):
                if distance == 0:
                    continue
                if distance < shortest_distance:
                    shortest_distance = distance
                    new_build_position = path[1]

            # run it through find placement in case it's blocked by some weird map feature
            if self.bot.game_info.map_name == 'Magannatha AIE':
                new_build_position = await self.bot.find_placement(
                    unit_type_id,
                    near=new_build_position,
                    max_distance=4,
                    placement_step=2,
                )

        elif unit_type_id == UnitTypeId.BUNKER:
            candidate: Point2 = None
            if rush_detected:
                # try to build near edge of high ground towards natural
                # high_ground_height = self.bot.get_terrain_height(self.bot.start_location)
                ramp_barracks = self.bot.structures.of_type(UnitTypeId.BARRACKS).closest_to(self.bot.main_base_ramp.barracks_correct_placement)
                candidates = [(depot_position + ramp_barracks.position) / 2 for depot_position in self.bot.main_base_ramp.corner_depots]
                candidate = max(candidates, key=lambda p: ramp_barracks.add_on_position.distance_to(p))
                candidate = candidate.towards(self.bot.main_base_ramp.top_center.towards(ramp_barracks.position, distance=2), distance=-1)
            else:
                ramp_position: Point2 = self.bot.main_base_ramp.bottom_center
                enemy_start: Point2 = self.bot.enemy_start_locations[0]
                candidate = ((ramp_position + self.map.natural_position) / 2).towards(enemy_start, distance=3)
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
                        near=base.position.towards(self.bot.game_info.map_center, distance=4),
                        placement_step=2,
                    )
                    break
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
                                    closest_townhall_to_enemy: Unit = self.map.get_closest_unit_by_path(ready_townhalls, self.bot.enemy_start_locations[0])
                                    preferred_townhalls = ready_townhalls.filter(lambda th: th.tag != closest_townhall_to_enemy.tag and not th.is_flying)
                            for townhall in preferred_townhalls:
                                new_build_position = await self.bot.find_placement(
                                    unit_type_id,
                                    near=townhall.position.towards(map_center, distance=8),
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
                    if new_build_position is None:
                        if retry_count > 0:
                            return None
                        retry_count += 1
                    # don't build near edge to avoid trapping units
                    elif unit_type_id != UnitTypeId.SUPPLYDEPOT:
                        edge_distance = self.map.get_distance_from_edge(new_build_position.rounded)
                        if edge_distance <= 3:
                            max_distance += 1
                            logger.debug(f"{new_build_position} is {edge_distance} from edge")
                            # accept defeat, is ok to do it sometimes
                            if max_distance > 50:
                                break
                            retry_count += 1
                            new_build_position = None
        if new_build_position is not None:
            if self.bot.enemy_units:
                threats = self.bot.enemy_units.filter(lambda u: u.can_attack_ground and u.type_id not in (UnitTypeId.DRONE, UnitTypeId.SCV, UnitTypeId.PROBE))
                if threats and threats.closer_than(10, new_build_position):
                    logger.debug(f"found enemy near proposed build position {new_build_position}, rejecting")
                    return None
                
            if unit_type_id == UnitTypeId.COMMANDCENTER and not rush_detected:
                self.attempted_expansion_positions[new_build_position] += 1
        return new_build_position

    def get_geysir(self) -> Union[Unit, None]:
        if self.bot.townhalls:
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
            if self.bot.gas_buildings:
                vespene_geysirs = vespene_geysirs.filter(
                    lambda geysir: self.bot.gas_buildings.closest_distance_to(geysir) > 1)
            if vespene_geysirs:
                return vespene_geysirs.closest_to(self.bot.start_location)
        return None

    def is_interrupted(self) -> bool:
        if self.unit_being_built and self.unit_being_built is not True and self.unit_being_built.build_progress == 1:
            return False
        
        if self.unit_in_charge is None:
            logger.debug(f"{self} builder is missing")
            return True

        self.check_idle: bool = (
            self.check_idle
            or self.upgrade_id is not None
            or self.unit_in_charge.type_id in self.production.facilities.keys()
            or (
                self.unit_in_charge.is_active and not self.unit_in_charge.is_gathering
            )
        )

        if self.check_idle:
            if self.unit_in_charge.is_idle and self.unit_in_charge.type_id != UnitTypeId.SCV:
                self.production.remove_type_from_facilty_queue(self.unit_in_charge, self.unit_type_id)
                logger.debug(f"unit_in_charge {self.unit_in_charge}")
                return True
            if self.unit_in_charge.tag in self.workers.assignments_by_worker:
                if self.workers.assignments_by_worker[self.unit_in_charge.tag].job_type != JobType.BUILD:
                    self.workers.update_job(self.unit_in_charge, JobType.BUILD)
                    if self.unit_type_id == UnitTypeId.REFINERY:
                        target = self.unit_being_built if self.unit_being_built else self.geysir
                        self.unit_in_charge(
                            self.bot.game_data.units[self.unit_type_id.value].creation_ability.id,
                            target=target,
                            queue=False,
                            subtract_cost=False,
                            can_afford_check=False,
                        )
                    else:
                        # unit.build subtracts the cost from self.bot.minerals/vespene so we need to use ability directly
                        target = self.unit_being_built if self.unit_being_built else self.position
                        self.unit_in_charge(
                            self.bot.game_data.units[self.unit_type_id.value].creation_ability.id,
                            target=target,
                            queue=False,
                            subtract_cost=False,
                            can_afford_check=False,
                        )
                if self.unit_being_built is None:
                    if self.unit_in_charge.distance_to_squared(self.position) < 9 and self.worker_in_position_time is None and self.bot.can_afford(self.unit_type_id):
                        self.worker_in_position_time = self.bot.time
                    elif self.worker_in_position_time is not None and self.bot.time - self.worker_in_position_time > 5 and self.cost.minerals <= self.bot.minerals and self.cost.vespene <= self.bot.vespene:
                        # position may be blocked
                        self.position = None
                        self.geysir = None
                        self.worker_in_position_time = None
                        self.workers.set_as_idle(self.unit_in_charge)
                        self.unit_in_charge = None
                        return True
                elif self.unit_in_charge.is_idle:
                    self.unit_in_charge.smart(self.unit_being_built)
        return False
    
    def cancel_construction(self):
        logger.debug(f"canceling build of {self.unit_being_built}")
        self.unit_being_built(AbilityId.CANCEL_BUILDINPROGRESS)
        self.last_cancel_time = self.bot.time
        self.unit_being_built = None
        if self.unit_in_charge and self.unit_in_charge.type_id == UnitTypeId.SCV:
            self.workers.update_assigment(self.unit_in_charge, JobType.IDLE, None)
            self.unit_in_charge = None
        self.position = None
        self.geysir = None
        self.worker_in_position_time = None
        self.is_in_progress = False
        self.check_idle = False
        self.start_time = None
        self.completed_time = None
