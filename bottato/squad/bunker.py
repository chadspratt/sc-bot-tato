from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit

from bottato.squad.squad import Squad
from bottato.unit_reference_helper import UnitReferenceHelper

class Bunker(Squad):
    def __init__(self, bot: BotAI, number: int, structure: Unit | None = None):
        super().__init__(bot, name=f"bunker{number}", color=(255, 255, 0))
        self.structure: Unit | None = structure
    
    def empty(self, destination: Unit | None = None):
        # command units to exit
        if self.structure:
            if destination:
                self.structure(AbilityId.RALLY_UNITS, destination.position)
            self.structure(AbilityId.UNLOADALL_BUNKER)
        self.units.clear()
    
    def pop(self):
        # command one unit to exit
        if self.units:
            unit = self.units.pop()
            # command unit to exit bunker
            return unit
        return None

    def salvage(self):
        # command to salvage the bunker
        if self.structure:
            self.structure(AbilityId.SALVAGEBUNKER_SALVAGE)

    def has_space(self):
        return self.structure and len(self.units) < 4
    
    def update_references(self):
        if self.structure:
            try:
                self.structure = UnitReferenceHelper.get_updated_unit_reference(self.structure)
            except UnitReferenceHelper.UnitNotFound:
                self.structure = None