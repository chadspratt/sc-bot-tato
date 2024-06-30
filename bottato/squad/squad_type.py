from sc2.ids.unit_typeid import UnitTypeId

from .composition import Composition


class SquadType():
    def __init__(self, name: str, composition: Composition) -> None:
        self.name = name
        self.composition = composition


SquadTypeDefinitions: dict[str, SquadType] = {
    'none': SquadType('none', Composition(initial_units=[])),
    'early marines': SquadType('none', Composition(initial_units=[UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.MARINE])),
    'worker scout': SquadType('worker scout', Composition(initial_units=[UnitTypeId.SCV])),
    'defensive tank': SquadType('defensive tank', Composition(initial_units=[UnitTypeId.SIEGETANK])),
    'reaper scouts': SquadType('reaper scouts',
                               Composition(initial_units=[UnitTypeId.REAPER],
                                           expansion_units=[UnitTypeId.REAPER],
                                           max_size=2)),
    'banshee harass': SquadType('banshee harass', Composition(initial_units=[UnitTypeId.BANSHEE], expansion_units=[UnitTypeId.BANSHEE])),
    'hellion harass': SquadType('hellion harass', Composition(initial_units=[UnitTypeId.HELLION, UnitTypeId.REAPER, UnitTypeId.HELLION])),
    'tanks with support': SquadType('tanks with support', Composition(
        initial_units=[UnitTypeId.SIEGETANK, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.RAVEN],
        expansion_units=[UnitTypeId.SIEGETANK, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.REAPER, UnitTypeId.VIKINGFIGHTER])),
    'anti air': SquadType('anti air', Composition(initial_units=[UnitTypeId.VIKINGFIGHTER, UnitTypeId.VIKINGFIGHTER])),
}
