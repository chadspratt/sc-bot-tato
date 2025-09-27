from __future__ import annotations

from loguru import logger

from sc2.position import Point2
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI

from bottato.mixins import TimerMixin, GeometryMixin, UnitReferenceMixin
from bottato.build_order import BuildOrder
from bottato.micro.structure_micro import StructureMicro
from bottato.enemy import Enemy
from bottato.economy.workers import JobType, Workers
from bottato.economy.production import Production
from bottato.military import Military
from bottato.squad.scouting import Scouting
from bottato.map.map import Map


class Commander(TimerMixin, GeometryMixin, UnitReferenceMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot

        self.map = Map(self.bot)
        # for loc in self.expansion_locations_list:
        #     self.map.get_path(self.game_info.player_start_location, loc)
        self.enemy: Enemy = Enemy(self.bot)
        self.my_workers: Workers = Workers(self.bot, self.enemy)
        self.military: Military = Military(self.bot, self.enemy, self.map, self.my_workers)
        self.structure_micro: StructureMicro = StructureMicro(self.bot, self.enemy)
        self.production: Production = Production(self.bot)
        self.build_order: BuildOrder = BuildOrder(
            "pig_b2gm", bot=self.bot, workers=self.my_workers, production=self.production, map=self.map
        )
        self.scouting = Scouting(self.bot, self.enemy, self.map, self.my_workers, self.military)
        self.new_damage_taken: dict[int, float] = {}
        self.stuck_units: list[Unit] = []
        self.rush_detected: bool = False
        # self.test_stuck = None

    async def command(self, iteration: int):
        self.start_timer("command")

        # self.map.refresh_map()
        # check for stuck units
        await self.detect_stuck_units(iteration)

        # XXX very slow
        self.map.update_influence_maps()

        await self.scout()
        if self.rush_detected:
            self.build_order.enact_rush_defense()
        # XXX extremely slow
        await self.military.manage_squads(iteration, self.build_order.get_blueprints())

        remaining_cap = self.build_order.remaining_cap
        if remaining_cap > 0:
            logger.debug(f"requesting at least {remaining_cap} supply of units for military")
            unit_request: list[UnitTypeId] = self.military.get_squad_request(remaining_cap)
            self.build_order.queue_units(unit_request)

        await self.structure_micro.execute()

        self.my_workers.attack_nearby_enemies()
        self.my_workers.distribute_idle()
        # self.my_workers.speed_mine()
        self.my_workers.drop_mules()

        # XXX slow
        await self.build_order.execute(self.military.army_ratio, self.rush_detected)
        self.new_damage_taken.clear()
        self.stop_timer("command")

    async def detect_stuck_units(self, iteration: int):
        self.start_timer("detect_stuck_units")
        if iteration % 3 == 0 and self.bot.workers:
            self.stuck_units.clear()
            miners = self.my_workers.availiable_workers_on_job(JobType.MINERALS)
            if not miners:
                return
            pathable_destination: Point2 = miners.furthest_to(self.bot.start_location).position
            if pathable_destination is not None:
                paths_to_check = [[unit, pathable_destination] for unit in self.military.main_army.units if unit.type_id != UnitTypeId.SIEGETANKSIEGED]
                if paths_to_check:
                    distances = await self.bot.client.query_pathings(paths_to_check)
                    for path, distance in zip(paths_to_check, distances):
                        if distance == 0:
                            self.bot.client.debug_text_3d("STUCK", path[0].position3d)
                            self.stuck_units.append(path[0])
                            logger.info(f"unit is stuck {path[0]}")
        else:
            self.stuck_units = self.get_updated_unit_references_by_tags([unit.tag for unit in self.stuck_units])
        self.stop_timer("detect_stuck_units")
        self.military.rescue_stuck_units(self.stuck_units)

    async def scout(self):
        self.start_timer("scout")
        self.scouting.update_visibility()
        await self.scouting.scout(self.new_damage_taken)
        self.rush_detected = self.scouting.rush_detected
        self.start_timer("scout")

    async def update_references(self):
        self.my_workers.update_references()
        self.military.update_references()
        self.enemy.update_references()
        self.build_order.update_references()
        await self.production.update_references()

    def update_started_structure(self, unit: Unit):
        self.build_order.update_started_structure(unit)

    def update_completed_structure(self, unit: Unit):
        self.build_order.update_completed_structure(unit)
        self.production.add_builder(unit)
        if unit.type_id == UnitTypeId.BUNKER:
            self.military.bunker.structure = unit

    def add_unit(self, unit: Unit):
        if unit.type_id not in (UnitTypeId.SCV, UnitTypeId.MULE):
            self.build_order.update_completed_unit(unit)
            logger.debug(f"assigned to {self.military.main_army.name}")
            self.military.add_to_main(unit)
        elif self.my_workers.add_worker(unit):
            # not an old worker that just popped out of a building
            self.build_order.update_completed_unit(unit)

    def log_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.tag not in self.new_damage_taken:
            self.new_damage_taken[unit.tag] = amount_damage_taken
        else:
            self.new_damage_taken[unit.tag] += amount_damage_taken
        if unit.is_structure:
            self.build_order.cancel_damaged_structure(unit, self.new_damage_taken[unit.tag])

    def remove_destroyed_unit(self, unit_tag: int):
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
        self.enemy.print_timers("enemy-")
        self.production.print_timers("production-")
