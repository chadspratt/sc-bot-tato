"""
https://github.com/DrInfy/sharpy-sc2/blob/develop/sharpy/managers/unit_value.py
"""
from sc2.ids.unit_typeid import UnitTypeId

BUILDINGS = {
    "2x2": {
        UnitTypeId.SUPPLYDEPOT,
        UnitTypeId.PYLON,
        UnitTypeId.DARKSHRINE,
        UnitTypeId.PHOTONCANNON,
        UnitTypeId.SHIELDBATTERY,
        UnitTypeId.TECHLAB,
        UnitTypeId.STARPORTTECHLAB,
        UnitTypeId.FACTORYTECHLAB,
        UnitTypeId.BARRACKSTECHLAB,
        UnitTypeId.REACTOR,
        UnitTypeId.STARPORTREACTOR,
        UnitTypeId.FACTORYREACTOR,
        UnitTypeId.BARRACKSREACTOR,
        UnitTypeId.MISSILETURRET,
        UnitTypeId.SPORECRAWLER,
        UnitTypeId.SPIRE,
        UnitTypeId.GREATERSPIRE,
        UnitTypeId.SPINECRAWLER,
    },
    "3x3": {
        UnitTypeId.GATEWAY,
        UnitTypeId.WARPGATE,
        UnitTypeId.CYBERNETICSCORE,
        UnitTypeId.FORGE,
        UnitTypeId.ROBOTICSFACILITY,
        UnitTypeId.ROBOTICSBAY,
        UnitTypeId.TEMPLARARCHIVE,
        UnitTypeId.TWILIGHTCOUNCIL,
        UnitTypeId.TEMPLARARCHIVE,
        UnitTypeId.STARGATE,
        UnitTypeId.FLEETBEACON,
        UnitTypeId.ASSIMILATOR,
        UnitTypeId.ASSIMILATORRICH,
        UnitTypeId.SPAWNINGPOOL,
        UnitTypeId.ROACHWARREN,
        UnitTypeId.HYDRALISKDEN,
        UnitTypeId.BANELINGNEST,
        UnitTypeId.EVOLUTIONCHAMBER,
        UnitTypeId.NYDUSNETWORK,
        UnitTypeId.NYDUSCANAL,
        UnitTypeId.EXTRACTOR,
        UnitTypeId.EXTRACTORRICH,
        UnitTypeId.INFESTATIONPIT,
        UnitTypeId.ULTRALISKCAVERN,
        UnitTypeId.BARRACKS,
        UnitTypeId.ENGINEERINGBAY,
        UnitTypeId.FACTORY,
        UnitTypeId.GHOSTACADEMY,
        UnitTypeId.STARPORT,
        UnitTypeId.FUSIONREACTOR,
        UnitTypeId.BUNKER,
        UnitTypeId.ARMORY,
        UnitTypeId.REFINERY,
        UnitTypeId.REFINERYRICH,
    },
    "5x5": {
        UnitTypeId.NEXUS,
        UnitTypeId.HATCHERY,
        UnitTypeId.HIVE,
        UnitTypeId.LAIR,
        UnitTypeId.COMMANDCENTER,
        UnitTypeId.ORBITALCOMMAND,
        UnitTypeId.PLANETARYFORTRESS,
    }
}

BUILDING_RADIUS = {}
for type_id in BUILDINGS["2x2"]:
    BUILDING_RADIUS[type_id] = 1
for type_id in BUILDINGS["3x3"]:
    BUILDING_RADIUS[type_id] = 2
for type_id in BUILDINGS["5x5"]:
    BUILDING_RADIUS[type_id] = 3

BUILDING_IDS = BUILDINGS["5x5"].union(BUILDINGS["3x3"]).union(BUILDINGS["2x2"])

destructibles = {
    "2x2": {
        UnitTypeId.ROCKS2X2NONCONJOINED,
        UnitTypeId.DEBRIS2X2NONCONJOINED
    },
    "4x4": {
        UnitTypeId.DESTRUCTIBLECITYDEBRIS4X4,
        UnitTypeId.DESTRUCTIBLEDEBRIS4X4,
        UnitTypeId.DESTRUCTIBLEICE4X4,
        UnitTypeId.DESTRUCTIBLEROCK4X4,
        UnitTypeId.DESTRUCTIBLEROCKEX14X4,
    },
    "4x2": {
        UnitTypeId.DESTRUCTIBLECITYDEBRIS2X4HORIZONTAL,
        UnitTypeId.DESTRUCTIBLEICE2X4HORIZONTAL,
        UnitTypeId.DESTRUCTIBLEROCK2X4HORIZONTAL,
        UnitTypeId.DESTRUCTIBLEROCKEX12X4HORIZONTAL,
    },
    "2x4": {
        UnitTypeId.DESTRUCTIBLECITYDEBRIS2X4VERTICAL,
        UnitTypeId.DESTRUCTIBLEICE2X4VERTICAL,
        UnitTypeId.DESTRUCTIBLEROCK2X4VERTICAL,
        UnitTypeId.DESTRUCTIBLEROCKEX12X4VERTICAL,
    },
    "6x2": {
        UnitTypeId.DESTRUCTIBLECITYDEBRIS2X6HORIZONTAL,
        UnitTypeId.DESTRUCTIBLEICE2X6HORIZONTAL,
        UnitTypeId.DESTRUCTIBLEROCK2X6HORIZONTAL,
        UnitTypeId.DESTRUCTIBLEROCKEX12X6HORIZONTAL,
    },
    "2x6": {
        UnitTypeId.DESTRUCTIBLECITYDEBRIS2X6VERTICAL,
        UnitTypeId.DESTRUCTIBLEICE2X6VERTICAL,
        UnitTypeId.DESTRUCTIBLEROCK2X6VERTICAL,
        UnitTypeId.DESTRUCTIBLEROCKEX12X6VERTICAL,
    },
    "4x12": {
        UnitTypeId.DESTRUCTIBLEROCKEX1VERTICALHUGE,
        UnitTypeId.DESTRUCTIBLEICEVERTICALHUGE
    },
    "12x4": {
        UnitTypeId.DESTRUCTIBLEROCKEX1HORIZONTALHUGE,
        UnitTypeId.DESTRUCTIBLEICEHORIZONTALHUGE
    },
    "6x6": {
        UnitTypeId.DESTRUCTIBLECITYDEBRIS6X6,
        UnitTypeId.DESTRUCTIBLEDEBRIS6X6,
        UnitTypeId.DESTRUCTIBLEICE6X6,
        UnitTypeId.DESTRUCTIBLEROCK6X6,
        UnitTypeId.DESTRUCTIBLEROCKEX16X6,
    },
    "BLUR": {
        UnitTypeId.DESTRUCTIBLECITYDEBRISHUGEDIAGONALBLUR,
        UnitTypeId.DESTRUCTIBLEDEBRISRAMPDIAGONALHUGEBLUR,
        UnitTypeId.DESTRUCTIBLEICEDIAGONALHUGEBLUR,
        UnitTypeId.DESTRUCTIBLEROCKEX1DIAGONALHUGEBLUR,
        UnitTypeId.DESTRUCTIBLERAMPDIAGONALHUGEBLUR,
    },
    "ULBR": {
        UnitTypeId.DESTRUCTIBLECITYDEBRISHUGEDIAGONALULBR,
        UnitTypeId.DESTRUCTIBLEDEBRISRAMPDIAGONALHUGEULBR,
        UnitTypeId.DESTRUCTIBLEICEDIAGONALHUGEULBR,
        UnitTypeId.DESTRUCTIBLEROCKEX1DIAGONALHUGEULBR,
        UnitTypeId.DESTRUCTIBLERAMPDIAGONALHUGEULBR,
    }
}
