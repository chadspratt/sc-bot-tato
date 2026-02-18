from __future__ import annotations

from loguru import logger

from cython_extensions.geometry import cy_distance_to, cy_towards
from sc2.bot_ai import BotAI
from sc2.game_data import Cost
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.building.build_order import BuildOrder
from bottato.economy.production import Production
from bottato.economy.workers import Workers
from bottato.enemy import Enemy
from bottato.enums import BuildType, CustomEffectType, Tactic, WorkerJobType
from bottato.log_helper import LogHelper
from bottato.map.destructibles import BUILDING_RADIUS
from bottato.map.map import Map
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.micro.structure_micro import StructureMicro
from bottato.military import Military
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.squad.bunker import Bunker
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.scouting import Scouting
from bottato.tactics import Tactics
from bottato.unit_reference_helper import UnitReferenceHelper


class Commander(GeometryMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot

        self.enemy: Enemy = Enemy(bot)
        self.map = Map(bot)

        self.intel = EnemyIntel(bot, self.map, self.enemy)
        self.tactics: Tactics = Tactics(bot, self.enemy, self.map, self.intel)
        self.production: Production = Production(bot, self.tactics)
        MicroFactory.set_common_objects(bot, self.tactics)
        self.structure_micro: StructureMicro = StructureMicro(bot, self.tactics)
        self.my_workers: Workers = Workers(bot, self.tactics)
        self.military: Military = Military(bot, self.tactics, self.my_workers)
        self.build_order: BuildOrder = BuildOrder(
            "pig_b2gm", bot, self.tactics, self.my_workers, self.production
        )
        self.scouting = Scouting(bot, self.tactics, self.my_workers, self.military)

        self.new_damage_by_unit: dict[int, float] = {}
        self.new_damage_by_position: dict[Point2, float] = {}
        self.pathable_position: Point2 | None = None
        self.stuck_units: Units = Units([], bot_object=bot)

    async def init_map(self):
        await self.map.init(self.intel.scouting_locations)
        self.scouting.init_scouting_routes()

    @timed_async
    async def command(self, iteration: int):
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(nearest_worker.position), 3, (255, 0, 0))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(self.bot.game_info.map_center), 1, (255, 255, 255))
        # ramp_to_natural_vector = (self.map.natural_position - self.bot.main_base_ramp.bottom_center).normalized
        # ramp_to_natural_perp_vector = Point2((-ramp_to_natural_vector.y, ramp_to_natural_vector.x))
        # toward_natural = Point2(cy_towards(self.bot.main_base_ramp.bottom_center, self.map.natural_position, 3))
        # candidates = [toward_natural + ramp_to_natural_perp_vector * 3, toward_natural - ramp_to_natural_perp_vector * 3]
        # candidates.sort(key=lambda p: cy_distance_to_squared(p, self.bot.game_info.map_center))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(toward_natural), 1, (0, 255, 0))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(candidates[0]), 1, (255, 255, 255))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(candidates[1]), 1, (255, 255, 0))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(Point2(cy_towards(toward_natural, self.bot.game_info.map_center, 3)), 1, (0, 0, 255))
        # self.bot.client.debug_sphere_out(self.convert_point2_to_3(nearest_worker.position, self.bot), 3, (255, 0, 0))

        await self.map.refresh_map() # fast
        # check for stuck units
        await self.detect_stuck_units(iteration) # fast

        self.map.update_influence_maps(self.new_damage_by_position) # fast
        BaseUnitMicro.reset_tag_sets()

        await self.structure_micro.execute(self.intel.army_ratio, self.stuck_units) # fast

        # do before build_order so scouts can be freed if they're done. mostly applies to building proxy barracks in response to early expansion
        await self.scout() # fast

        # XXX slow, 17% of command time
        remaining_resources: Cost = await self.build_order.execute(self.structure_micro.destinations)


        self.add_custom_effects_to_avoid()
        # very slow, 70% of command time
        await self.military.manage_squads(iteration,
                                          self.intel.get_newest_enemy_base(),
                                          self.intel.enemy_builds_detected,
                                          self.intel.proxy_buildings)

        await self.my_workers.attack_nearby_enemies(self.intel.enemy_builds_detected) # ultra fast
        await self.my_workers.redistribute_workers(remaining_resources, self.intel.enemy_builds_detected)
        await self.my_workers.speed_mine() # slow, 15% of command time
        # if self.bot.time > 240:
        #     logger.debug(f"minerals gathered: {self.bot.state.score.collected_minerals}")
        self.my_workers.drop_mules() # fast

        self.new_damage_by_unit.clear()
        self.new_damage_by_position.clear()

    @timed
    def add_custom_effects_to_avoid(self):
        blueprints = self.build_order.get_blueprints()
        for blueprint in blueprints:
            position = blueprint.get_position()
            if position:
                BaseUnitMicro.add_custom_effect(CustomEffectType.BUILDING_FOOTPRINT,
                                                position=position,
                                                radius=BUILDING_RADIUS[blueprint.get_unit_type_id()],
                                                start_time=self.bot.time,
                                                duration=0.3)
        for nova in self.bot.enemy_units.of_type(UnitTypeId.DISRUPTORPHASED):
            BaseUnitMicro.add_custom_effect(CustomEffectType.ENEMY,
                                            position=nova,
                                            radius=1.5 + 1,
                                            start_time=self.bot.time,
                                            duration=0.05)
        # for baneling in self.bot.enemy_units.of_type(UnitTypeId.BANELING):
        #     BaseUnitMicro.add_custom_effect(CustomEffectType.ENEMY,
        #                                     position=baneling,
        #                                     radius=2.2,
        #                                     start_time=self.bot.time,
        #                                     duration=0.05)

    @timed_async
    async def detect_stuck_units(self, iteration: int):
        if iteration % 3 == 0 and self.bot.workers and self.bot.units.of_type(UnitTypeId.MEDIVAC):
            self.stuck_units.clear()
            # skip if ramp depots are raised
            if self.unit_is_closer_than(self.bot.main_base_ramp.top_center, self.bot.structures(UnitTypeId.SUPPLYDEPOT), 5):
                return
            path_checking_position = await self.map.get_path_checking_position()
            if path_checking_position is not None:
                paths_to_check = [[unit, path_checking_position] for unit in self.bot.units
                                  if unit.type_id != UnitTypeId.SIEGETANKSIEGED and not unit.is_flying
                                  and unit.position.manhattan_distance(self.bot.start_location) < 60]
                if paths_to_check:
                    distances = await self.bot.client.query_pathings(paths_to_check)
                    for path, distance in zip(paths_to_check, distances):
                        if distance == 0:
                            self.bot.client.debug_text_3d("STUCK", path[0].position3d)
                            self.stuck_units.append(path[0])
                            logger.debug(f"unit is stuck {path[0]}")
        self.military.rescue_stuck_units(self.stuck_units)
        await self.enemy.detect_stuck_enemies(iteration)

    @timed_async
    async def scout(self):
        self.scouting.update_visibility()
        await self.intel.update()
        await self.scouting.scout(self.new_damage_by_unit)

    @timed_async
    async def update_references(self):
        self.my_workers.update_references(self.build_order.get_assigned_worker_tags())
        self.military.update_references()
        self.tactics.update_references()
        self.enemy.update_references()
        await self.build_order.update_references()
        await self.production.update_references()
        self.stuck_units = UnitReferenceHelper.get_updated_unit_references(self.stuck_units)

    def update_started_structure(self, unit: Unit):
        self.build_order.update_started_structure(unit)

    def update_completed_structure(self, unit: Unit):
        self.build_order.update_completed_structure(unit)
        LogHelper.write_log_to_db(f'Building', unit.type_id.name)
        self.production.add_builder(unit)
        if unit.type_id == UnitTypeId.BARRACKS and len(self.bot.structures(UnitTypeId.BARRACKS)) == 1:
            # set rally point for first barracks away from ramp
            rally_point = Point2(cy_towards(unit.position, self.bot.main_base_ramp.top_center, -2))
            unit(AbilityId.RALLY_UNITS, rally_point)
        elif unit.type_id in (UnitTypeId.BARRACKS, UnitTypeId.FACTORY, UnitTypeId.STARPORT):
            unit(AbilityId.RALLY_UNITS, self.bot.game_info.map_center)
        elif unit.type_id == UnitTypeId.BUNKER:
            if not self.military.top_ramp_bunker.structure:
                distance_to_top_ramp = cy_distance_to(unit.position, self.bot.main_base_ramp.barracks_correct_placement) # type: ignore
                if distance_to_top_ramp < 6:
                    self.military.top_ramp_bunker.structure = unit
                    return
            if not self.military.natural_bunker.structure:
                # not top ramp, assume natural
                self.military.natural_bunker.structure = unit
                return
            new_bunker = Bunker(self.bot, self.enemy, len(self.military.bunkers), unit)
            self.military.bunkers.append(new_bunker)
            self.military.squads.append(new_bunker)
            return

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
        self.military.log_damage(unit)

    def remove_destroyed_unit(self, unit_tag: int):
        destroyed_unit = UnitReferenceHelper.units_by_tag.get(unit_tag)
        if destroyed_unit and destroyed_unit.is_mine and not destroyed_unit.is_structure and destroyed_unit.type_id != UnitTypeId.MULE:
            rounded_position = destroyed_unit.position.rounded
            if rounded_position not in self.new_damage_by_position:
                self.new_damage_by_position[rounded_position] = destroyed_unit.health
            else:
                self.new_damage_by_position[rounded_position] += destroyed_unit.health
        self.enemy.record_death(unit_tag)
        self.military.record_death(unit_tag)
        self.my_workers.record_death(unit_tag)
        if destroyed_unit and destroyed_unit.type_id == UnitTypeId.BUNKER and destroyed_unit.build_progress == 1.0:
            self.build_order.add_to_build_queue([UnitTypeId.BUNKER], queue=self.build_order.priority_queue)

    def add_upgrade(self, upgrade: UpgradeId):
        logger.debug(f"upgrade completed {upgrade}")
        self.build_order.update_completed_upgrade(upgrade)
        LogHelper.write_log_to_db('Upgrade complete', upgrade.name)
