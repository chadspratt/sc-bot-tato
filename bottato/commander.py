from __future__ import annotations

from loguru import logger

from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.game_state import EffectData

from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import TimerMixin, GeometryMixin, UnitReferenceMixin
from bottato.build_order import BuildOrder
from bottato.micro.structure_micro import StructureMicro
from bottato.enemy import Enemy
from bottato.economy.workers import Workers
from bottato.economy.production import Production
from bottato.military import Military
from bottato.squad.scouting import Scouting
from bottato.map.map import Map
from bottato.enums import RushType, WorkerJobType


class Commander(TimerMixin, GeometryMixin, UnitReferenceMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot

        self.map = Map(self.bot)
        # for loc in self.expansion_locations_list:
        #     self.map.get_path(self.game_info.player_start_location, loc)
        self.enemy: Enemy = Enemy(self.bot)
        MicroFactory.set_common_objects(self.bot, self.enemy, self.map)
        self.my_workers: Workers = Workers(self.bot, self.enemy, self.map)
        self.military: Military = Military(self.bot, self.enemy, self.map, self.my_workers)
        self.structure_micro: StructureMicro = StructureMicro(self.bot, self.enemy)
        self.production: Production = Production(self.bot)
        self.build_order: BuildOrder = BuildOrder(
            "pig_b2gm", bot=self.bot, workers=self.my_workers, production=self.production, map=self.map
        )
        self.scouting = Scouting(self.bot, self.enemy, self.map, self.my_workers, self.military)
        self.new_damage_by_unit: dict[int, float] = {}
        self.new_damage_by_position: dict[Point2, float] = {}
        self.pathable_position: Point2 | None = None
        self.stuck_units: Units = Units([], bot_object=self.bot)
        self.rush_detected_type: RushType = RushType.NONE
        self.units_by_tag: dict[int, Unit] = {}

    async def command(self, iteration: int):
        self.start_timer("command")
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(self.bot.main_base_ramp.bottom_center), 1, (255, 0, 0))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(self.bot.game_info.map_center), 1, (255, 255, 255))
        # ramp_to_natural_vector = (self.map.natural_position - self.bot.main_base_ramp.bottom_center).normalized
        # ramp_to_natural_perp_vector = Point2((-ramp_to_natural_vector.y, ramp_to_natural_vector.x))
        # toward_natural = self.bot.main_base_ramp.bottom_center.towards(self.map.natural_position, 3)
        # candidates = [toward_natural + ramp_to_natural_perp_vector * 3, toward_natural - ramp_to_natural_perp_vector * 3]
        # candidates.sort(key=lambda p: p.distance_to(self.bot.game_info.map_center))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(toward_natural), 1, (0, 255, 0))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(candidates[0]), 1, (255, 255, 255))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(candidates[1]), 1, (255, 255, 0))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(toward_natural.towards(self.bot.game_info.map_center, 3)), 1, (0, 0, 255))

        await self.map.refresh_map() # fast
        # check for stuck units
        await self.detect_stuck_units(iteration) # fast

        self.map.update_influence_maps(self.new_damage_by_position) # fast
        BaseUnitMicro.reset_tanks_being_retreated_to()

        await self.structure_micro.execute(self.rush_detected_type) # unknown speed

        # XXX slow, 17% of command time
        await self.build_order.execute(self.military.army_ratio, self.rush_detected_type, self.enemy)

        await self.scout() # unknown speed
        # self.rush_detected_type = RushType.STANDARD if self.bot.time > 70 else RushType.NONE

        # XXX extremely slow
        self.start_timer("avoid blueprints")
        blueprints = self.build_order.get_blueprints()
        for blueprint in blueprints:
            position = blueprint.get_position()
            if position:
                self.create_fake_grenade(position)
        self.stop_timer("avoid blueprints")
        # very slow, 53% of command time
        await self.military.manage_squads(iteration,
                                          self.build_order.get_blueprints(),
                                          self.scouting.get_newest_enemy_base(),
                                          self.rush_detected_type)

        await self.my_workers.attack_nearby_enemies() # ultra fast
        self.my_workers.distribute_idle() # fast
        await self.my_workers.speed_mine() # slow, 20% of command time
        # if self.bot.time > 240:
        #     logger.debug(f"minerals gathered: {self.bot.state.score.collected_minerals}")
        self.my_workers.drop_mules() # fast

        self.new_damage_by_unit.clear()
        self.new_damage_by_position.clear()
        self.stop_timer("command")

    class FakeGrenadeProto:
        def __init__(self, position: Point2):
            self.radius = 0.5
            self.tag = 0
            self.unit_type = UnitTypeId.KD8CHARGE.value
            self.pos = position
            self.alliance = 3  # Effect

    def create_fake_grenade(self, position: Point2):
        fake_reaper_grenade = self.FakeGrenadeProto(position)
        self.bot.state.effects.add(EffectData(fake_reaper_grenade, fake=True))

    async def detect_stuck_units(self, iteration: int):
        self.start_timer("detect_stuck_units")
        if iteration % 3 == 0 and self.bot.workers and self.bot.units.of_type(UnitTypeId.MEDIVAC):
            self.stuck_units.clear()
            if self.pathable_position is None:
                self.pathable_position = await self.bot.find_placement(UnitTypeId.MISSILETURRET,self.bot.game_info.map_center, 25, placement_step = 5)
            else:
                # check that position still pathable
                miners = self.my_workers.availiable_workers_on_job(WorkerJobType.MINERALS)
                if not miners:
                    return
                furthest_miner = miners.furthest_to(self.pathable_position)
                if await self.bot.client.query_pathing(furthest_miner, self.pathable_position) is None:
                    self.pathable_position = await self.bot.find_placement(UnitTypeId.MISSILETURRET,self.bot.game_info.map_center, 25, placement_step = 5)
            # pathable_destination: Point2 = miners.furthest_to(self.bot.start_location).position
            if self.pathable_position is not None:
                paths_to_check = [[unit, self.pathable_position] for unit in self.military.main_army.units
                                  if unit.type_id != UnitTypeId.SIEGETANKSIEGED and not unit.is_flying
                                  and unit.position.manhattan_distance(self.bot.start_location) < 60]
                if paths_to_check:
                    distances = await self.bot.client.query_pathings(paths_to_check)
                    for path, distance in zip(paths_to_check, distances):
                        if distance == 0:
                            self.bot.client.debug_text_3d("STUCK", path[0].position3d)
                            self.stuck_units.append(path[0])
                            logger.debug(f"unit is stuck {path[0]}")
        self.stop_timer("detect_stuck_units")
        self.military.rescue_stuck_units(self.stuck_units)

    async def scout(self):
        self.start_timer("scout")
        self.scouting.update_visibility()
        await self.scouting.scout(self.new_damage_by_unit, self.units_by_tag)
        self.rush_detected_type = await self.scouting.rush_detected_type
        self.stop_timer("scout")

    async def update_references(self, units_by_tag: dict[int, Unit]):
        self.start_timer("update_references")
        self.units_by_tag = units_by_tag
        self.my_workers.update_references(units_by_tag, self.build_order.get_assigned_worker_tags())
        self.military.update_references(units_by_tag)
        self.enemy.update_references(units_by_tag)
        await self.build_order.update_references(units_by_tag)
        await self.production.update_references(units_by_tag)
        self.stuck_units = self.get_updated_unit_references(self.stuck_units, self.bot, units_by_tag)
        self.stop_timer("update_references")

    def update_started_structure(self, unit: Unit):
        self.build_order.update_started_structure(unit)

    def update_completed_structure(self, unit: Unit):
        self.build_order.update_completed_structure(unit)
        self.production.add_builder(unit)
        if unit.type_id == UnitTypeId.BARRACKS and len(self.bot.structures(UnitTypeId.BARRACKS)) == 1:
            # set rally point for first barracks away from ramp
            unit(AbilityId.RALLY_UNITS, unit.position.towards(self.bot.main_base_ramp.top_center, -2)) # type: ignore
        elif unit.type_id in (UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT):
            unit(AbilityId.RALLY_UNITS, self.bot.game_info.map_center)
        elif unit.type_id == UnitTypeId.BUNKER:
            if not self.military.bunker.structure:
                self.military.bunker.structure = unit
            elif not self.military.bunker2.structure:
                self.military.bunker2.structure = unit

    def add_unit(self, unit: Unit):
        if unit.type_id not in (UnitTypeId.SCV, UnitTypeId.MULE):
            self.build_order.update_completed_unit(unit)
            logger.debug(f"assigned to {self.military.main_army.name}")
            self.military.add_to_main(unit)
        elif self.my_workers.add_worker(unit):
            # not an old worker that just popped out of a building
            self.build_order.update_completed_unit(unit)

    def log_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.is_mine and not unit.is_structure:
            rounded_position = unit.position.rounded
            if rounded_position not in self.new_damage_by_position:
                self.new_damage_by_position[rounded_position] = amount_damage_taken
            else:
                self.new_damage_by_position[rounded_position] += amount_damage_taken
        if unit.tag not in self.new_damage_by_unit:
            self.new_damage_by_unit[unit.tag] = amount_damage_taken
        else:
            self.new_damage_by_unit[unit.tag] += amount_damage_taken
        if unit.is_structure:
            self.build_order.cancel_damaged_structure(unit, self.new_damage_by_unit[unit.tag])

    def remove_destroyed_unit(self, unit_tag: int):
        destroyed_unit = self.units_by_tag.get(unit_tag)
        if destroyed_unit and destroyed_unit.is_mine and not destroyed_unit.is_structure and destroyed_unit.type_id != UnitTypeId.MULE:
            rounded_position = destroyed_unit.position.rounded
            if rounded_position not in self.new_damage_by_position:
                self.new_damage_by_position[rounded_position] = destroyed_unit.health
            else:
                self.new_damage_by_position[rounded_position] += destroyed_unit.health
        self.enemy.record_death(unit_tag)
        self.military.record_death(unit_tag)
        self.my_workers.record_death(unit_tag)

    def add_upgrade(self, upgrade: UpgradeId):
        logger.debug(f"upgrade completed {upgrade}")
        self.build_order.update_completed_upgrade(upgrade)

    def print_all_timers(self, interval: int = 0):
        self.print_timers("commander-")
        self.build_order.print_timers("build_order-")
        self.my_workers.print_timers("my_workers-")
        self.map.print_timers("map-")
        self.military.print_timers("military-")
        self.military.main_army.print_timers("main_army-")
        self.military.main_army.parent_formation.print_timers("main_formation-")
        self.enemy.print_timers("enemy-")
        self.production.print_timers("production-")
        self.structure_micro.print_timers("structure_micro-")
