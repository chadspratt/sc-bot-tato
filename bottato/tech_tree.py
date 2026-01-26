from typing import Dict, List

from sc2.constants import TERRAN_TECH_REQUIREMENT
# from sc2.dicts.unit_trained_from import UNIT_TRAINED_FROM
from sc2.ids.unit_typeid import UnitTypeId

TECH_TREE: Dict[UnitTypeId, List[UnitTypeId]] = {}
for k, v in TERRAN_TECH_REQUIREMENT.items():
    TECH_TREE[k] = [v]
# for k, v in UNIT_TRAINED_FROM.items():
#     if k in TECH_TREE:
#         TECH_TREE[k].extend(v)
#     else:
#         TECH_TREE[k] = list(v)
TECH_TREE[UnitTypeId.RAVEN] = [UnitTypeId.STARPORTTECHLAB]
TECH_TREE[UnitTypeId.BANSHEE] = [UnitTypeId.STARPORTTECHLAB]
TECH_TREE[UnitTypeId.SIEGETANK] = [UnitTypeId.FACTORYTECHLAB]
TECH_TREE[UnitTypeId.THOR] = [UnitTypeId.ARMORY, UnitTypeId.FACTORYTECHLAB]
TECH_TREE[UnitTypeId.MARAUDER] = [UnitTypeId.BARRACKSTECHLAB]
TECH_TREE[UnitTypeId.GHOST] = [UnitTypeId.GHOSTACADEMY, UnitTypeId.BARRACKSTECHLAB]
TECH_TREE[UnitTypeId.FACTORYTECHLAB] = [UnitTypeId.FACTORY]
TECH_TREE[UnitTypeId.STARPORTTECHLAB] = [UnitTypeId.STARPORT]
TECH_TREE[UnitTypeId.REAPER] = [UnitTypeId.BARRACKS]
TECH_TREE[UnitTypeId.BATTLECRUISER] = [UnitTypeId.FUSIONCORE, UnitTypeId.STARPORTTECHLAB]
