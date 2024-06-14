from sc2.ids.unit_typeid import UnitTypeId

from .composition import Composition


class SquadType():
    def __init__(self, name: str, composition: Composition) -> None:
        self.name = name
        self.composition = composition


class SquadTypeDefinition():
    _squad_types: dict[str, SquadType] = {
        'worker scout': SquadType('worker scout', Composition(initial_units=[UnitTypeId.SCV])),
        'defensive tank': SquadType('defensive tank', Composition(initial_units=[UnitTypeId.SIEGETANK])),
        'reaper scouts': SquadType('reaper scouts', Composition(initial_units=[UnitTypeId.REAPER], expansion_units=[UnitTypeId.REAPER])),
        'banshee harass': SquadType('banshee harass', Composition(initial_units=[UnitTypeId.BANSHEE], expansion_units=[UnitTypeId.BANSHEE])),
        'hellion harass': SquadType('hellion harass', Composition(initial_units=[UnitTypeId.HELLION, UnitTypeId.REAPER, UnitTypeId.HELLION])),
        'tanks with support': SquadType('tanks with support', Composition(
            initial_units=[UnitTypeId.SIEGETANK, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.RAVEN],
            expansion_units=[UnitTypeId.SIEGETANK, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.MARINE, UnitTypeId.REAPER, UnitTypeId.VIKING])),
        'anti air': SquadType('anti air', Composition(initial_units=[UnitTypeId.VIKING, UnitTypeId.VIKING])),
    }

    def get(self, squad_type_name: str) -> SquadType:
        return self._squad_types[squad_type_name]
