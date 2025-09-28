import enum
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


class BuildStep(UnitReferenceMixin, GeometryMixin, TimerMixin):
    unit_type_id: UnitTypeId = None
    upgrade_id: UpgradeId = None
    unit_in_charge: Optional[Unit] = None
    unit_being_built: Optional[Unit] = None
    pos: Union[Unit, Point2] = None
    geysir: Unit = None
    check_idle: bool = False
    last_cancel_time: float = -10
    start_time: int = None
    completed_time: int = None
    worker_in_position_time: int = None

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
            if self.pos:
                self.bot.client.debug_line_out(self.unit_in_charge, self.convert_point2_to_3(self.pos), (255, 130, 0))
            if self.unit_type_id:
                self.bot.client.debug_text_world(
                    self.unit_type_id.name, self.unit_in_charge.position3d)
            elif self.upgrade_id:
                self.bot.client.debug_text_world(
                    self.upgrade_id.name, self.unit_in_charge.position3d)
        if self.pos:
            self.bot.client.debug_box2_out(self.convert_point2_to_3(self.pos), 0.5)
            self.bot.client.debug_text_world(
                self.unit_type_id.name, Point3((*self.pos, 10))
            )
        if self.unit_being_built is not None and self.unit_being_built is not True:
            logger.debug(f"unit being built {self.unit_being_built}")
            self.bot.client.debug_box2_out(self.unit_being_built, 0.75)

    def update_references(self):
        logger.debug(f"unit in charge: {self.unit_in_charge}")
        try:
            self.unit_in_charge = self.get_updated_unit_reference(self.unit_in_charge)
            if self.unit_in_charge.type_id == UnitTypeId.SCV:
                for assignment in self.workers.assignments_by_worker.values():
                    if assignment.unit.tag == self.unit_in_charge.tag:
                        # ensure worker assignment is correct
                        self.workers.update_assigment(self.unit_in_charge, job_type=JobType.BUILD, target=self.unit_being_built)
                    elif assignment.target and self.unit_being_built and assignment.target.tag == self.unit_being_built.tag:
                        # check that no other workers think they are assigned to this build
                        self.workers.set_as_idle(assignment.unit)
        except self.UnitNotFound:
            self.unit_in_charge = None
        if isinstance(self.unit_being_built, Unit):
            try:
                self.unit_being_built = self.get_updated_unit_reference(self.unit_being_built)
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

    async def execute_scv_build(self, special_locations: SpecialLocations, rush_defense_enacted: bool = False) -> ResponseCode:
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
                self.pos = self.geysir.position
                if self.unit_in_charge is None:
                    self.unit_in_charge = self.workers.get_builder(self.pos)
                if self.unit_in_charge is None:
                    response = ResponseCode.NO_BUILDER
                else:
                    build_response = self.unit_in_charge.build_gas(self.geysir)
        else:
            if self.pos is None or (self.unit_being_built is None and self.start_time is not None and self.start_time - self.bot.time > 5):
                self.pos = await self.find_placement(self.unit_type_id, special_locations, rush_defense_enacted)
            if self.pos is None:
                response = ResponseCode.NO_LOCATION
            else:
                if self.unit_in_charge is None:
                    self.unit_in_charge = self.workers.get_builder(self.pos)
                if self.unit_in_charge is None:
                    response = ResponseCode.NO_BUILDER
                else:
                    logger.debug(
                        f"Trying to build structure {self.unit_type_id} at {self.pos}"
                    )
                    self.unit_in_charge.move(self.pos)

                    if self.unit_being_built is None:
                        build_response = self.unit_in_charge.build(
                            self.unit_type_id, self.pos
                        )
                    else:
                        self.start_time = self.bot.time
                        build_response = self.unit_in_charge.smart(self.unit_being_built)
                        logger.debug(f"{self.unit_in_charge} in charge is doing {self.unit_in_charge.orders}")
        if build_response is not None:
            response = ResponseCode.SUCCESS if build_response else ResponseCode.FAILED

        return response
    
    async def position_worker(self, special_locations: SpecialLocations):
        if UnitTypeId.SCV in self.builder_type:
            if self.pos is None:
                self.pos = await self.find_placement(self.unit_type_id, special_locations)
            if self.pos is not None:
                if self.unit_in_charge is None:
                    self.unit_in_charge = self.workers.get_builder(self.pos)
                if self.unit_in_charge is not None:
                    self.unit_in_charge.move(self.pos)

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
                self.pos = self.unit_in_charge.add_on_position
        elif self.unit_type_id == UnitTypeId.SCV:
            # scv
            facility_candidates = self.bot.townhalls.filter(lambda x: x.is_ready and x.is_idle)
            facility_candidates.sort(key=lambda x: x.type_id == UnitTypeId.COMMANDCENTER)
            self.unit_in_charge = facility_candidates[0] if facility_candidates else None
        else:
            facility_candidates = self.bot.structures.filter(lambda x: x.type_id in self.builder_type and x.is_ready and x.is_idle)
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

    async def find_placement(self, unit_type_id: UnitTypeId, special_locations: SpecialLocations, rush_defense_enacted: bool = False) -> Union[Point2, None]:
        new_build_position = None
        if unit_type_id == UnitTypeId.COMMANDCENTER:
            new_build_position = await self.bot.get_next_expansion()
        elif unit_type_id == UnitTypeId.BUNKER:
            candidate: Point2 = None
            if rush_defense_enacted:
                candidate = self.bot.main_base_ramp.top_center
            else:
                ramp_position: Point2 = self.bot.main_base_ramp.bottom_center
                enemy_start: Point2 = self.bot.enemy_start_locations[0]
                candidate = ((ramp_position + self.map.natural_position) / 2).towards(enemy_start, distance=2)
            retry_count = 0
            while not new_build_position or new_build_position.distance_to(self.map.natural_position) < 4:
                new_build_position = await self.bot.find_placement(
                                    unit_type_id,
                                    near=candidate)
                retry_count += 1
                if retry_count > 5:
                    break
        elif unit_type_id == UnitTypeId.MISSILETURRET:
            bases = self.bot.structures.of_type({UnitTypeId.COMMANDCENTER, UnitTypeId.ORBITALCOMMAND, UnitTypeId.PLANETARYFORTRESS})
            turrets = self.bot.structures.of_type(UnitTypeId.MISSILETURRET)
            for base in bases:
                if not turrets or self.closest_distance(base, turrets) > 10:
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
                while True:
                    try:
                        if self.bot.townhalls:
                            preferred_townhalls = self.bot.townhalls
                            if prefer_earlier_bases and len(self.bot.townhalls.ready) > 1 and retry_count == 0:
                                preferred_townhalls = self.bot.townhalls.ready.closest_n_units(self.bot.start_location, len(self.bot.townhalls.ready) - 1)
                            new_build_position = await self.bot.find_placement(
                                unit_type_id,
                                near=preferred_townhalls.random.position.towards(map_center, distance=8),
                                placement_step=2,
                                addon_place=addon_place,
                                max_distance=max_distance,
                            )
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
                        continue
                    # don't build near edge to avoid trapping units
                    if unit_type_id != UnitTypeId.SUPPLYDEPOT:
                        edge_distance = self.map.get_distance_from_edge(new_build_position.rounded)
                        if edge_distance <= 3:
                            max_distance += 1
                            logger.debug(f"{new_build_position} is {edge_distance} from edge")
                            # accept defeat, is ok to do it sometimes
                            if max_distance > 50:
                                break
                            retry_count += 1
                            continue
                    # try to not block addons
                    in_progress = [u for u in self.bot.structures
                                   if u.type_id in (UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT)
                                   and u.build_progress < 1]
                    for no_addon_facility in in_progress + self.production.get_no_addon_facilities():
                        if no_addon_facility.add_on_position.distance_to(new_build_position) < BUILDING_RADIUS[unit_type_id] + 1:
                            if retry_count > 3:
                                return None
                            retry_count += 1
                            break
                    else:
                        break
        if new_build_position is not None:
            if self.bot.enemy_units.filter(lambda u: u.can_attack_ground).closer_than(10, new_build_position):
                logger.debug(f"found enemy near proposed build position {new_build_position}, rejecting")
                return None
        return new_build_position

    def get_geysir(self) -> Union[Unit, None]:
        # All the vespene geysirs nearby, including ones with a refinery on top of it
        # command_centers = bot.townhalls
        if self.bot.townhalls:
            vespene_geysirs = self.bot.vespene_geyser.in_distance_of_group(
                distance=10, other_units=self.bot.townhalls.ready
            )
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
                # self.unit_in_charge.move(self.pos)
                if self.unit_being_built is not None and self.unit_being_built is not True:
                    self.unit_in_charge.smart(self.unit_being_built)
                else:
                    if self.unit_in_charge.distance_to(self.pos) < 3 and self.worker_in_position_time is None and self.bot.can_afford(self.unit_type_id):
                        self.worker_in_position_time = self.bot.time
                    elif self.worker_in_position_time is not None and self.bot.time - self.worker_in_position_time > 2:
                        # position may be blocked
                        self.pos = None
                        self.geysir = None
                        self.worker_in_position_time = None
                        self.workers.set_as_idle(self.unit_in_charge)
                        self.unit_in_charge = None
                        return True
                    if self.unit_type_id == UnitTypeId.REFINERY:
                        self.unit_in_charge(
                            self.bot.game_data.units[self.unit_type_id.value].creation_ability.id,
                            target=self.geysir,
                            queue=False,
                            subtract_cost=False,
                            can_afford_check=False,
                        )
                        # self.unit_in_charge.build_gas(self.geysir)
                    else:
                        # unit.build subtracts the cost from self.bot.minerals/vespene so we need to use ability directly
                        self.unit_in_charge(
                            self.bot.game_data.units[self.unit_type_id.value].creation_ability.id,
                            target=self.pos,
                            queue=False,
                            subtract_cost=False,
                            can_afford_check=False,
                        )
                        # self.unit_in_charge.build(self.unit_type_id, self.pos)
        return False
    
    def cancel_construction(self):
        logger.debug(f"canceling build of {self.unit_being_built}")
        self.unit_being_built(AbilityId.CANCEL_BUILDINPROGRESS)
        self.last_cancel_time = self.bot.time
        self.unit_being_built = None
        if self.unit_in_charge and self.unit_in_charge.type_id == UnitTypeId.SCV:
            self.workers.update_assigment(self.unit_in_charge, JobType.IDLE, None)
            self.unit_in_charge = None
        self.pos = None
        self.geysir = None
        self.worker_in_position_time = None
        self.is_in_progress = False
        self.check_idle = False
        self.start_time = None
        self.completed_time = None
