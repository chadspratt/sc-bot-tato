
from loguru import logger
from typing import Dict, List

from cython_extensions.geometry import cy_distance_to_squared, cy_towards
from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.micro.medivac_micro import MedivacMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.squad.formation_squad import FormationSquad
from bottato.squad.squad import Squad
from bottato.unit_reference_helper import UnitReferenceHelper


class StuckRescue(Squad):
    def __init__(self, bot: BotAI, main_army: FormationSquad, squads_by_unit_tag: Dict[int, Squad | None]):
        super().__init__(bot, name="stuck rescue", color=(255, 0, 255))
        self.main_army = main_army
        self.squads_by_unit_tag = squads_by_unit_tag

        self.transport: Unit | None = None
        self.is_loaded: bool = False
        self.dropoff: Point2 | None = None

        self.pending_unload: set[int] = set()
        self.medivac_micro: MedivacMicro = MicroFactory.get_unit_micro(UnitTypeId.MEDIVAC) # type: ignore

    def update_references(self):
        if self.transport:
            try:
                self.transport = UnitReferenceHelper.get_updated_unit_reference(self.transport)
            except UnitReferenceHelper.UnitNotFound:
                self.transport = None
                self.is_loaded = False
                self.dropoff = None

    async def rescue(self, stuck_units: List[Unit], path_checking_position: Point2 | None):
        if self.pending_unload:
            tags_to_check = list(self.pending_unload)
            for tag in tags_to_check:
                try:
                    unit = UnitReferenceHelper.get_updated_unit_reference_by_tag(tag)
                    self.main_army.recruit(unit)
                    self.squads_by_unit_tag[unit.tag] = self.main_army
                    self.pending_unload.remove(tag)
                except UnitReferenceHelper.UnitNotFound:
                    pass
        if self.transport and self.is_loaded:
            if not self.transport.passengers_tags:
                self.is_loaded = False
                self.dropoff = None
            elif stuck_units and path_checking_position is not None:
                await self._try_early_unload(stuck_units, path_checking_position)
            elif not self.medivac_micro.use_booster(self.transport):
                self.dropoff = Point2(cy_towards(self.main_army.position, self.bot.start_location, 8))
                self.transport.move(self.dropoff)
                if cy_distance_to_squared(self.transport.position, self.dropoff) < 25:
                    self.transport(AbilityId.UNLOADALLAT, self.transport, True)
                    for tag in self.transport.passengers_tags:
                        self.pending_unload.add(tag)
            return
        if not stuck_units:
            if self.transport:
                if self.transport.cargo_used > 0:
                    self.is_loaded = True
                else:
                    self.main_army.recruit(self.transport)
                    self.transport = None
                    self.is_loaded = False
            return
        if self.transport is None:
            medivacs = self.bot.units(UnitTypeId.MEDIVAC)
            if not medivacs:
                return
            medivacs_with_space = medivacs.filter(lambda unit: unit.cargo_left > 0)
            if not medivacs_with_space:
                return
            # use medivac with least energy
            self.transport = medivacs_with_space.sorted(lambda u: u.energy)[0]
            if self.transport.tag in self.squads_by_unit_tag and self.squads_by_unit_tag[self.transport.tag] is not None:
                self.squads_by_unit_tag[self.transport.tag].remove(self.transport) # type: ignore
                self.squads_by_unit_tag[self.transport.tag] = None

        cargo_left = self.transport.cargo_left
        cargo_needed = sum(u.cargo_size for u in stuck_units)
        if not self.medivac_micro.use_booster(self.transport):
            transport_position = self.transport.position
            closest_stuck_unit = min(stuck_units, key=lambda u: u.distance_to(transport_position))
            for unit in stuck_units:
                if cargo_left < unit.cargo_size:
                    break
                elif unit.tag == closest_stuck_unit.tag:
                    self.transport(AbilityId.LOAD, closest_stuck_unit)
                unit.smart(self.transport)
                cargo_left -= unit.cargo_size
            if cargo_left == self.transport.cargo_left:
                # everything loaded (next frame)
                self.is_loaded = True
            elif self.transport.cargo_used > 0 and cargo_needed > cargo_left and cargo_needed <= self.transport.cargo_max:
                # can't fit remaining stuck units now, but can in one full trip — drop off partial load first
                self.is_loaded = True

    async def _try_early_unload(self, stuck_units: List[Unit], path_checking_position: Point2):
        """While transporting, check if passengers can be dropped at current position
        to free cargo for remaining stuck units."""
        if not self.transport or self.medivac_micro.use_booster(self.transport):
            return
        distance = await self.bot.client.query_pathing(
            self.transport.position, path_checking_position
        )
        if distance is None:
            # current position is not pathable, keep heading to army
            self.dropoff = Point2(cy_towards(self.main_army.position, self.bot.start_location, 8))
            self.transport.move(self.dropoff)
            if cy_distance_to_squared(self.transport.position, self.dropoff) < 25:
                self.transport(AbilityId.UNLOADALLAT, self.transport, True)
                for tag in self.transport.passengers_tags:
                    self.pending_unload.add(tag)
            return
        # position is pathable — unload all passengers to free space
        logger.debug(f"stuck_rescue: dropping passengers early at {self.transport.position}")
        self.transport(AbilityId.UNLOADALLAT, self.transport)
        for tag in self.transport.passengers_tags:
            self.pending_unload.add(tag)
        self.is_loaded = False
        self.dropoff = None