from __future__ import annotations

from typing import Dict, List, Set

from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId

from bottato.squad.creep_clearing_squad import CreepClearingSquad
from bottato.squad.hunting_squad import HuntingSquad


class HuntingSquadType():
    def __init__(self, unit_composition: dict[UnitTypeId, int], target_types: Set[UnitTypeId], start_time: float = 0,
                 squad_class: type | None = None):
        self.unit_composition = unit_composition
        self.target_types = target_types
        self.start_time = start_time
        self.squad_class = squad_class if squad_class else HuntingSquad
        self.name = f"Hunt {'/'.join([t.name for t in target_types])}"

hunting_squad_types: Dict[Race, List[HuntingSquadType]] = {
    Race.Zerg: [
        HuntingSquadType({UnitTypeId.VIKINGFIGHTER: 1},
                        {UnitTypeId.OVERLORD, UnitTypeId.OVERSEER}, 180),
        HuntingSquadType({UnitTypeId.RAVEN: 1, UnitTypeId.MARINE: 3},
                        {UnitTypeId.CREEPTUMORBURROWED, UnitTypeId.CREEPTUMOR, UnitTypeId.CREEPTUMORQUEEN}, 300,
                        squad_class=CreepClearingSquad),
    ],
    Race.Terran: [
        HuntingSquadType({UnitTypeId.VIKINGFIGHTER: 1},
                        {UnitTypeId.MEDIVAC}, 240),
    ]

}


