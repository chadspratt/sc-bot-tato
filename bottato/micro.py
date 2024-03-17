from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit

from .build_step import BuildStep


class Squad:
    def __init__(
        self,
        bot: BotAI,
        composition: dict[UnitTypeId, int] = None,
        color: tuple[int] = (0, 255, 0),
        name: str = "fuckwits",
    ):
        self.bot = bot
        self.name = name
        self.composition = composition or {}
        self.color = color
        self._units: list[Unit] = []

    def wants(self, unit_type_id: UnitTypeId) -> int:
        _wants = self.composition.get(unit_type_id, 0)
        logger.info(f"{self.name} squad wants {_wants} {unit_type_id.name}")
        return _wants

    def has(self, unit_type_id: UnitTypeId) -> int:
        _has = sum([1 for u in self._units if u.type_id is unit_type_id])
        logger.info(f"{self.name} squad wants {_has} {unit_type_id.name}")
        return _has

    def needs(self, unit_type_id: UnitTypeId) -> bool:
        return 0 < self.wants(unit_type_id) < self.has(unit_type_id)

    def refresh_unit_references(self):
        logger.info("So refreshing!")
        _units = []
        for unit in self.units:
            try:
                _units.append(self.bot.all_units.by_tag(unit.tag))
            except KeyError:
                logger.info(f"Couldn't find unit {unit}!")
        self._units = _units

    def draw_debug_box(self):
        for unit in self._units:
            self.bot.client.debug_box2_out(unit, color=self.color)

    def recruit(self, unit: Unit):
        logger.info(f"Recruiting {unit} into {self.name} squad")
        self._units.append(unit)

    @property
    def units(self):
        return list(self._units)

    def remove(self, unit: Unit):
        logger.info(f"Removing {unit} from {self.name} squad")
        try:
            self._units.remove(unit)
        except ValueError:
            logger.info("Unit not found in squad")

    def transfer(self, unit: Unit, to_squad: "Squad"):
        self.remove(unit)
        to_squad.recruit(unit)


class Formation:
    def __init__(self, position: Point2, front: Point2, units: list[Unit] = []):
        self.units = units
        self.position = position
        self.front = front


class Micro:
    def __init__(self, bot: BotAI) -> None:
        self.last_worker_stop = 0
        self.bot: BotAI = bot
        self.unassigned_army = Squad(bot, )
        self.squads = [
            Squad(bot, composition={UnitTypeId.REAPER: 2}, color=(0, 0, 255), name="alpha"),
            Squad(bot, composition={UnitTypeId.HELLION: 2, UnitTypeId.REAPER: 1}, color=(255, 255, 0), name="burninate"),
            Squad(bot, composition={UnitTypeId.CYCLONE: 1, UnitTypeId.MARINE: 4, UnitTypeId.RAVEN: 1}, color=(255, 0, 255), name="seek"),
            Squad(bot, composition={UnitTypeId.SIEGETANK: 1, UnitTypeId.MARINE: 4, UnitTypeId.RAVEN: 1}, color=(255, 0, 0), name="destroy"),
            Squad(bot, composition={UnitTypeId.SIEGETANK: 1, UnitTypeId.MARINE: 2, UnitTypeId.RAVEN: 1}, color=(0, 255, 255), name="defend"),
        ]
        self.formations = []

    def manage_squads(self):
        self.unassigned_army.refresh_unit_references()
        self.unassigned_army.draw_debug_box()
        for unassigned in self.unassigned_army.units:
            for squad in self.squads:
                if squad.needs(unassigned):
                    self.unassigned_army.transfer(unassigned, squad)
        for squad in self.squads:
            squad.refresh_unit_references()
            squad.draw_debug_box()

    def manage_formations(self):
        # create formation if there are none
        if not self.formations:
            self
        # gather unassigned units to formations

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

    def get_mineral_gatherer(self, for_building: Unit):
        local_minerals_tags = {
            mineral.tag
            for mineral in self.mineral_field if mineral.distance_to(for_building) <= 12
        }
        return self.bot.workers.filter(
            lambda unit: unit.order_target in local_minerals_tags and not unit.is_carrying_minerals
        ).closest_to(for_building)

    def get_vespene_gatherer(self, for_building: Unit):
        gas_building_tags = [b.tag for b in self.bot.gas_buildings.ready]
        return self.bot.workers.filter(
            lambda unit: unit.order_target in gas_building_tags and not unit.is_carrying_vespene
        ).closest_to(for_building)

    async def _distribute_workers(self, pending_build_steps: list[BuildStep]):
        cooldown = 3
        if self.bot.time - self.last_worker_stop > cooldown:
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
                    continue
                for _ in range(-_surplus_harvesters):
                    gatherer = self.get_mineral_gatherer(building)
                    if gatherer is not None:
                        logger.info("switching worker")
                        gatherer.smart(building)
                        self.last_worker_stop = self.bot.time
        elif vespene_needed < 0:
            logger.info("saturate minerals")
            for building in self.bot.townhalls.ready:
                _surplus_harvesters = building.surplus_harvesters
                if _surplus_harvesters > 0:
                    continue
                for _ in range(-_surplus_harvesters):
                    gatherer = self.get_vespene_gatherer(building)
                    if gatherer is not None:
                        logger.info("switching worker")
                        gatherer.smart(building)
                        self.last_worker_stop = self.bot.time
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
