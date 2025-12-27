from bottato.squad.squad import Squad
from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId


class Bunker(Squad):
    def __init__(self, bot: BotAI, number: int):
        super().__init__(bot=bot, name=f"bunker{number}", color=(255, 255, 0))
        self.structure = None
    
    def empty(self):
        # command units to exit
        if self.structure:
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
    
    def update_references(self, units_by_tag):
        if self.structure:
            try:
                self.structure = self.get_updated_unit_reference(self.structure, self.bot, units_by_tag)
            except self.UnitNotFound:
                self.structure = None