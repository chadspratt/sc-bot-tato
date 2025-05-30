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
from sc2.game_data import Cost
from sc2.protocol import ConnectionAlreadyClosedError, ProtocolError

from bottato.map.map import Map
from bottato.mixins import UnitReferenceMixin, GeometryMixin, TimerMixin
from bottato.economy.workers import Workers
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
    check_idle: bool = False
    last_cancel: float = -10
    completed_time: int = None

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
        target = (
            f"{self.unit_being_built} {self.unit_being_built.build_progress}"
            if self.unit_being_built and self.unit_being_built is not True
            else self.unit_type_id
        )
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
        except self.UnitNotFound:
            self.unit_in_charge = None
        if isinstance(self.unit_being_built, Unit):
            try:
                self.unit_being_built = self.get_updated_unit_reference(self.unit_being_built)
            except self.UnitNotFound:
                self.unit_being_built = None

    async def execute(self, special_locations: SpecialLocations, needed_resources: Cost = None) -> ResponseCode:
        self.start_timer("build_step.execute inner")
        response = None
        if self.upgrade_id:
            self.start_timer(f"build_step.execute_upgrade {self.upgrade_id}")
            response = self.execute_upgrade()
            self.stop_timer(f"build_step.execute_upgrade {self.upgrade_id}")
        elif UnitTypeId.SCV in self.builder_type:
            self.start_timer(f"build_step.execute_scv_build {self.unit_type_id}")
            response = await self.execute_scv_build(special_locations, needed_resources)
            self.stop_timer(f"build_step.execute_scv_build {self.unit_type_id}")
        else:
            self.start_timer(f"build_step.execute_facility_build {self.unit_type_id}")
            response = self.execute_facility_build()
            self.stop_timer(f"build_step.execute_facility_build {self.unit_type_id}")
        if response == ResponseCode.SUCCESS:
            self.start_timer("build_step.draw_debug_box")
            self.draw_debug_box()
            self.stop_timer("build_step.draw_debug_box")
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

    async def execute_scv_build(self, special_locations: SpecialLocations, needed_resources: Cost = None) -> ResponseCode:
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
            empty_gas: Union[Unit, None] = self.get_geysir()
            if empty_gas is None:
                response = ResponseCode.NO_FACILITY
            else:
                self.pos = empty_gas.position
                if self.unit_in_charge is None:
                    self.unit_in_charge = self.workers.get_builder(self.pos, needed_resources)
                if self.unit_in_charge is None:
                    response = ResponseCode.NO_BUILDER
                else:
                    build_response = self.unit_in_charge.build_gas(empty_gas)
        else:
            self.pos = await self.find_placement(self.unit_type_id, special_locations)
            if self.pos is None:
                response = ResponseCode.NO_LOCATION
            else:
                if self.unit_in_charge is None:
                    self.unit_in_charge = self.workers.get_builder(self.pos, needed_resources)
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
                        build_response = self.unit_in_charge.smart(self.unit_being_built)
                        logger.debug(f"{self.unit_in_charge} in charge is doing {self.unit_in_charge.orders}")
        if build_response is not None:
            response = ResponseCode.SUCCESS if build_response else ResponseCode.FAILED

        return response

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
        elif self.unit_type_id == UnitTypeId.SCV:
            # scv
            facility_candidates = self.bot.townhalls.filter(lambda x: x.is_ready and x.is_idle)
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

    async def find_placement(self, unit_type_id: UnitTypeId, special_locations: SpecialLocations) -> Union[Point2, None]:
        new_build_position = None
        if unit_type_id == UnitTypeId.COMMANDCENTER:
            new_build_position = await self.bot.get_next_expansion()
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
                map_center = self.bot.game_info.map_center
                max_distance = 20
                while True:
                    try:
                        if self.bot.townhalls:
                            new_build_position = await self.bot.find_placement(
                                unit_type_id,
                                near=self.bot.townhalls.random.position.towards(map_center, distance=8),
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
                        return None
                    # don't build near edge to avoid trapping units
                    if unit_type_id != UnitTypeId.SUPPLYDEPOT:
                        edge_distance = self.map.get_distance_from_edge(new_build_position.rounded)
                        if edge_distance <= 3:
                            max_distance += 1
                            logger.debug(f"{new_build_position} is {edge_distance} from edge")
                            # accept defeat, is ok to do it sometimes
                            if max_distance > 50:
                                break
                            continue
                    # try to not block addons
                    in_progress = [u for u in self.bot.structures
                                   if u.type_id in (UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT)
                                   and u.build_progress < 1]
                    for no_addon_facility in in_progress + self.production.get_no_addon_facilities():
                        if no_addon_facility.add_on_position.distance_to(new_build_position) < BUILDING_RADIUS[unit_type_id] + 1:
                            break
                    else:
                        break
        return new_build_position

    def get_geysir(self) -> Union[Unit, None]:
        # All the vespene geysirs nearby, including ones with a refinery on top of it
        # command_centers = bot.townhalls
        if self.bot.townhalls:
            vespene_geysirs = self.bot.vespene_geyser.in_distance_of_group(
                distance=10, other_units=self.bot.townhalls
            )
            for vespene_geysir in vespene_geysirs:
                if self.bot.gas_buildings.filter(
                    lambda unit: unit.distance_to(vespene_geysir) < 1
                ):
                    continue
                return vespene_geysir
        return None

    def is_interrupted(self) -> bool:
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
            if self.unit_in_charge.is_idle:
                self.production.remove_type_from_facilty_queue(self.unit_in_charge, self.unit_type_id)
                logger.debug(f"unit_in_charge {self.unit_in_charge}")
                return True
        return False
