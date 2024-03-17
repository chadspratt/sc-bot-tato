from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit

from .build_step import BuildStep
from .squad import Squad


class Formation:
    def __init__(self, position: Point2, front: Point2, units: list[Unit] = []):
        self.units = units
        self.position = position
        self.front = front


class Military:
    def __init__(self, bot: BotAI) -> None:
        self.bot: BotAI = bot
        self.unassigned_army = Squad(bot, )
        self.squads = [
            Squad(bot, composition={UnitTypeId.REAPER: 2}, color=(0, 0, 255), name="alpha"),
            Squad(bot, composition={UnitTypeId.HELLION: 2, UnitTypeId.REAPER: 1}, color=(255, 255, 0), name="burninate"),
            Squad(bot, composition={UnitTypeId.CYCLONE: 1, UnitTypeId.MARINE: 4, UnitTypeId.RAVEN: 1}, color=(255, 0, 255), name="seek"),
            Squad(bot, composition={UnitTypeId.SIEGETANK: 1, UnitTypeId.MARINE: 4, UnitTypeId.RAVEN: 1}, color=(255, 0, 0), name="destroy"),
            Squad(bot, composition={UnitTypeId.SIEGETANK: 1, UnitTypeId.MARINE: 2, UnitTypeId.RAVEN: 1}, color=(0, 255, 255), name="defend"),
        ]

    def muster_workers(self, position: Point2, count: int = 5):
        pass
        
    def manage_squads(self, enemies_in_view: list[Unit]):
        self.unassigned_army.manage_paperwork()
        self.unassigned_army.draw_debug_box()
        for unassigned in self.unassigned_army.units:
            for squad in self.squads:
                if squad.needs(unassigned):
                    self.unassigned_army.transfer(unassigned, squad)
                    break
        for squad in self.squads:
            squad.manage_paperwork()
            squad.draw_debug_box()
            if squad.is_full:
                logger.info(f"squad {squad.name} is full")
                map_center = self.bot.game_info.map_center
                staging_location = self.bot.start_location.towards(
                    map_center, distance=10
                )
                squad.move(staging_location)
        for squad in self.squads:
            if squad.is_full:
                squad.attack(enemies_in_view, is_priority=True)
        # if not alpha_squad.has_orders and self.enemies_in_view:
        #     alpha_squad.attack(self.enemies_in_view[0])
    
    def manage_formations(self):
        # create formation if there are none
        if not self.formations:
            self
        # gather unassigned units to formations


class Micro:
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = 0
        self.bot: BotAI = bot
        self.military = Military(bot)
        self.formations = []
        self.enemies_in_view = []

    def manage_squads(self):
        self.military.manage_squads(self.enemies_in_view)
        self.enemies_in_view = []

    def adjust_supply_depots_for_enemies(self):
        # Raise depos when enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.distance_to(depot) < 10:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    break
        # Lower depos when no enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.distance_to(depot) < 15:
                    break
            else:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    def get_mineral_gatherer_near_building(self, for_building: Unit):
        if not self.bot.workers:
            return None
        local_minerals_tags = {
            mineral.tag
            for mineral in self.bot.mineral_field if mineral.distance_to(for_building) <= 12
        }
        return self.bot.workers.filter(
            lambda unit: unit.order_target in local_minerals_tags and not unit.is_carrying_minerals
        ).closest_to(for_building)

    def get_vespene_gatherer_near_building(self, for_building: Unit):
        if not self.bot.workers:
            return None
        gas_building_tags = [b.tag for b in self.bot.gas_buildings.ready]
        vespene_workers = self.bot.workers.filter(
            lambda unit: unit.order_target in gas_building_tags and not unit.is_carrying_vespene
        )
        if vespene_workers:
            return vespene_workers.closest_to(for_building)

    async def _distribute_workers(self, pending_build_steps: list[BuildStep]):
        if not pending_build_steps:
            return
        cooldown = 3
        if self.bot.time - self.last_worker_stop <= cooldown:
            logger.info("Distribute workers is on cooldown")
            return
        minerals_needed = -self.bot.minerals
        vespene_needed = -self.bot.vespene

        for idx, build_step in enumerate(pending_build_steps):
            # how much _more_ do we need for the next three steps of each resource
            minerals_needed += build_step.cost.minerals
            vespene_needed += build_step.cost.vespene
            if idx > 2 and (minerals_needed > 0 or vespene_needed > 0):
                break
        logger.info(
            f"Shortages projected: vespene ({vespene_needed}),  "
            f"minerals ({minerals_needed}), lookahead {idx} steps"
        )

        if minerals_needed < 0:
            logger.info("saturate vespine")
            for building in self.bot.gas_buildings.ready:
                _surplus_harvesters = building.surplus_harvesters
                if _surplus_harvesters > 0:
                    # no space for more workers
                    continue
                logger.info(f"need {-_surplus_harvesters} harvesters at {building}")
                for _ in range(-_surplus_harvesters):
                    gatherer = self.get_mineral_gatherer_near_building(building)
                    logger.info(f"found mineral gatherer near {building}")
                    if gatherer is not None:
                        logger.info("switching worker to vespene")
                        gatherer.smart(building)
                        self.last_worker_stop = self.bot.time
        elif vespene_needed < 0:
            logger.info("saturate minerals")
            for building in self.bot.townhalls.ready:
                _surplus_harvesters = building.surplus_harvesters
                if _surplus_harvesters > 0:
                    # no space for more workers
                    continue
                logger.info(f"need {-_surplus_harvesters} harvesters at {building}")
                local_minerals = {
                    mineral
                    for mineral in self.bot.mineral_field if mineral.distance_to(building) <= 12
                }
                logger.info(f"local minerals {local_minerals}")

                target_mineral = max(local_minerals, key=lambda mineral: mineral.mineral_contents, default=None)
                logger.info(f"mineral patch {target_mineral}")
                if target_mineral:
                    for _ in range(-_surplus_harvesters):
                        gatherer = self.get_vespene_gatherer_near_building(building)
                        if gatherer is None:
                            break
                        logger.info(f"moving vespene gatherer near {building} to minerals {target_mineral}")
                        gatherer.gather(target_mineral)
                        self.last_worker_stop = self.bot.time
                        break

        else:
            # both positive
            # balance ratio
            pass

    async def distribute_workers(self, pending_build_steps: list[BuildStep]):
        await self._distribute_workers(pending_build_steps)
        await self.bot.distribute_workers()
        logger.info(
            [
                worker.orders[0].ability.id
                for worker in self.bot.workers
                if worker.orders
            ]
        )
