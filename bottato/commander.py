from __future__ import annotations

from loguru import logger

from sc2.position import Point2
from sc2.ids.upgrade_id import UpgradeId
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.bot_ai import BotAI

from bottato.mixins import TimerMixin, GeometryMixin
from bottato.build_order import BuildOrder
from bottato.micro.structure_micro import StructureMicro
from bottato.enemy import Enemy
from bottato.economy.workers import Workers
from bottato.economy.production import Production
from bottato.military import Military
from bottato.map.map import Map


class Commander(TimerMixin, GeometryMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot

        self.map = Map(self.bot)
        # for loc in self.expansion_locations_list:
        #     self.map.get_path(self.game_info.player_start_location, loc)
        self.enemy: Enemy = Enemy(self.bot)
        self.my_workers: Workers = Workers(self.bot, self.enemy)
        self.military: Military = Military(self.bot, self.enemy, self.map, self.my_workers)
        self.structure_micro: StructureMicro = StructureMicro(self.bot)
        self.production: Production = Production(self.bot)
        self.build_order: BuildOrder = BuildOrder(
            "tvt2", bot=self.bot, workers=self.my_workers, production=self.production, map=self.map
        )

    async def command(self, iteration: int):
        self.start_timer("command")

        # self.map.refresh_map()
        # check for stuck units
        # pathable_destination: Point2 = self.military.main_army.parent_formation.front_center
        pathable_destination: Point2 = self.bot.workers.furthest_to(self.bot.start_location).position
        if pathable_destination is not None:
            paths_to_check = [[unit, pathable_destination] for unit in self.military.main_army.units]
            if paths_to_check:
                distances = await self.bot.client.query_pathings(paths_to_check)
                for path, distance in zip(paths_to_check, distances):
                    if distance == 0:
                        logger.info(f"unit is stuck {path[0]}")

        self.start_timer("update_influence_maps")
        # XXX very slow
        self.map.update_influence_maps(self.build_order.get_pending_buildings())
        self.stop_timer("update_influence_maps")

        self.start_timer("military.manage_squads")
        # XXX extremely slow
        await self.military.manage_squads(iteration)
        self.stop_timer("military.manage_squads")

        # squads_to_fill: List[BaseSquad] = [self.military.get_squad_request()]
        remaining_cap = self.build_order.remaining_cap
        if remaining_cap > 0:
            self.start_timer("military.get_squad_request")
            logger.debug(f"requesting at least {remaining_cap} supply of units for military")
            unit_request: list[UnitTypeId] = self.military.get_squad_request(remaining_cap)
            self.stop_timer("military.get_squad_request")
            self.start_timer("build_order.queue_military")
            self.build_order.queue_units(unit_request)
            self.stop_timer("build_order.queue_military")

        self.start_timer("structure_micro.execute")
        await self.structure_micro.execute()
        self.stop_timer("structure_micro.execute")

        self.my_workers.attack_nearby_enemies()
        self.start_timer("my_workers.distribute_idle")
        self.my_workers.distribute_idle()
        self.stop_timer("my_workers.distribute_idle")
        self.start_timer("my_workers.speed_mine")
        # self.my_workers.speed_mine()
        self.stop_timer("my_workers.speed_mine")
        self.my_workers.drop_mules()

        self.start_timer("build_order.execute")
        # XXX slow
        await self.build_order.execute(self.military.army_ratio)
        self.stop_timer("build_order.execute")
        self.stop_timer("command")

    async def update_references(self):
        self.start_timer("my_workers.update_references")
        self.my_workers.update_references()
        self.stop_timer("my_workers.update_references")
        self.start_timer("military.update_references")
        self.military.update_references()
        self.stop_timer("military.update_references")
        self.start_timer("enemy.update_references")
        self.enemy.update_references()
        self.stop_timer("enemy.update_references")
        self.start_timer("build_order.update_references")
        self.build_order.update_references()
        self.stop_timer("build_order.update_references")
        self.start_timer("production.update_references")
        await self.production.update_references()
        self.stop_timer("production.update_references")

    def update_started_structure(self, unit: Unit):
        self.build_order.update_started_structure(unit)

    def update_completed_structure(self, unit: Unit):
        self.build_order.update_completed_structure(unit)
        self.production.add_builder(unit)

    def add_unit(self, unit: Unit):
        if unit.type_id not in (UnitTypeId.SCV, UnitTypeId.MULE):
            self.build_order.update_completed_unit(unit)
            logger.debug(f"assigned to {self.military.main_army.name}")
            self.military.add_to_main(unit)
        elif self.my_workers.add_worker(unit):
            # not an old worker that just popped out of a building
            self.build_order.update_completed_unit(unit)

    def log_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.is_structure:
            self.build_order.cancel_damaged_structure(unit, amount_damage_taken)
        else:
            self.military.report_damage(unit, amount_damage_taken)

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
