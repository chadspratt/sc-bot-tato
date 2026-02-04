
from typing import Dict, List

from cython_extensions.geometry import cy_distance_to_squared, cy_towards
from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

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

    def update_references(self):
        if self.transport:
            try:
                self.transport = UnitReferenceHelper.get_updated_unit_reference(self.transport)
            except UnitReferenceHelper.UnitNotFound:
                self.transport = None
                self.is_loaded = False
                self.dropoff = None

    def rescue(self, stuck_units: List[Unit]):
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
            else:
                self.dropoff = Point2(cy_towards(self.main_army.position, self.bot.start_location, 8))
                self.transport.move(self.dropoff)
                if cy_distance_to_squared(self.transport.position, self.dropoff) < 25:
                    self.transport(AbilityId.UNLOADALLAT, self.transport)
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
        for unit in stuck_units:
            if cargo_left >= unit.cargo_size:
                self.transport(AbilityId.LOAD, unit, True)
                cargo_left -= unit.cargo_size
            else:
                break
        if cargo_left == self.transport.cargo_left:
            # everything loaded (next frame)
            self.is_loaded = True