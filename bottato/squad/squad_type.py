from sc2.ids.unit_typeid import UnitTypeId

from .composition import Composition


class SquadType():
    def __init__(self, name: str, composition: Composition) -> None:
        self.name = name
        self.composition = composition


SquadTypeDefinitions: dict[str, SquadType] = {
    'none': SquadType('none', Composition({})),
    'early marines': SquadType('none', Composition({UnitTypeId.MARINE: 8})),
    'worker scout': SquadType('worker scout', Composition({UnitTypeId.SCV: 1})),
    'defensive tank': SquadType('defensive tank', Composition({UnitTypeId.SIEGETANK: 1})),
    'reaper scouts': SquadType('reaper scouts', Composition({UnitTypeId.REAPER: 1})),
    'reaper skirmish': SquadType('reaper scouts', Composition({UnitTypeId.REAPER: 4})),
    'banshee harass': SquadType('banshee harass', Composition({UnitTypeId.BANSHEE: 1})),
    'hellion harass': SquadType('hellion harass', Composition({UnitTypeId.HELLION: 2, UnitTypeId.REAPER: 1})),
    'tanks with support': SquadType('tanks with support', Composition(
        {UnitTypeId.SIEGETANK: 1, UnitTypeId.MARINE: 4, UnitTypeId.RAVEN: 1, UnitTypeId.MEDIVAC: 1, UnitTypeId.BANSHEE: 1})),
    'full army': SquadType('full army', Composition({
        UnitTypeId.SIEGETANK: 2,
        UnitTypeId.MARAUDER: 2,
        UnitTypeId.MARINE: 6,
        UnitTypeId.RAVEN: 1,
        UnitTypeId.MEDIVAC: 2,
        UnitTypeId.BANSHEE: 2,
        UnitTypeId.VIKINGFIGHTER: 3,
        UnitTypeId.THOR: 1,
        UnitTypeId.BATTLECRUISER: 1
    })),
    'anti air': SquadType('anti air', Composition({UnitTypeId.VIKINGFIGHTER: 1})),
}
