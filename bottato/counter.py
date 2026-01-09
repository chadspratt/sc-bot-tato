import math
from typing import List

from sc2.ids.unit_typeid import UnitTypeId
from sc2.units import Units
from sc2.unit import Unit

from bottato.unit_types import UnitTypes

class Counter():
    counters: dict[UnitTypeId, dict[UnitTypeId, float]] = {
        # Protoss units
        UnitTypeId.ADEPT: { # 2
            UnitTypeId.MARAUDER: 0.5,
            UnitTypeId.SIEGETANK: 0.1
        },
        UnitTypeId.ARCHON: { # 4
            UnitTypeId.THOR: 0.6,
            UnitTypeId.GHOST: 0.4,
            UnitTypeId.SIEGETANK: 0.2
        },
        UnitTypeId.CARRIER: { # 6
            UnitTypeId.VIKINGFIGHTER: 3
        },
        UnitTypeId.COLOSSUS: { # 6
            UnitTypeId.VIKINGFIGHTER: 2.5
        },
        UnitTypeId.DARKTEMPLAR: { # 2
            UnitTypeId.RAVEN: 0.2,
            UnitTypeId.MARINE: 2
        },
        UnitTypeId.DISRUPTOR: { # 4
            UnitTypeId.BANSHEE: 0.5, # 1.5
            UnitTypeId.THOR: 0.4 # 2.4
        },
        UnitTypeId.FLEETBEACON: {
            UnitTypeId.VIKINGFIGHTER: 8
        },
        UnitTypeId.HIGHTEMPLAR: { # 2
            UnitTypeId.GHOST: 0.7, # 2.1
            UnitTypeId.SIEGETANK: 0.1
        },
        UnitTypeId.IMMORTAL: { # 4
            UnitTypeId.BANSHEE: 0.5, # 1.5
            UnitTypeId.MARINE: 1.5,
            UnitTypeId.SIEGETANK: 0.2 # 1
        },
        UnitTypeId.MOTHERSHIP: { # 8
            UnitTypeId.VIKINGFIGHTER: 4,
        },
        UnitTypeId.OBSERVER: { # 1
            UnitTypeId.MARINE: 3
        },
        UnitTypeId.ORACLE: { # 3
            UnitTypeId.VIKINGFIGHTER: 1.5, # 3
        },
        UnitTypeId.PHOENIX: { # 2
            UnitTypeId.VIKINGFIGHTER: 1
        },
        UnitTypeId.SENTRY: { # 2
            UnitTypeId.MARINE: 2
        },
        UnitTypeId.STALKER: { # 2
            UnitTypeId.MARAUDER: 0.5,
            # UnitTypeId.MARINE: 1.5,
            UnitTypeId.WIDOWMINE: 0.3,
            UnitTypeId.SIEGETANK: 0.2
        },
        UnitTypeId.STARGATE: {
            UnitTypeId.VIKINGFIGHTER: 5
        },
        UnitTypeId.TEMPEST: { # 4
            UnitTypeId.VIKINGFIGHTER: 3,
            UnitTypeId.CYCLONE: 0.3
        },
        UnitTypeId.VOIDRAY: { # 4
            UnitTypeId.VIKINGFIGHTER: 2
        },
        UnitTypeId.WARPPRISM: { # 2
            UnitTypeId.VIKINGFIGHTER: 1
        },
        UnitTypeId.ZEALOT: { # 2
            UnitTypeId.SIEGETANK: 0.2, # 1
            UnitTypeId.MARINE: 1,
            UnitTypeId.WIDOWMINE: 0.2
        },
        # Terran units
        UnitTypeId.BANSHEE: { # 3
            UnitTypeId.MARINE: 0.4,
            UnitTypeId.VIKINGFIGHTER: 0.6
        },
        UnitTypeId.BATTLECRUISER: { # 6
            UnitTypeId.VIKINGFIGHTER: 2.5,
            UnitTypeId.MARINE: 2
        },
        UnitTypeId.CYCLONE: { # 3
            UnitTypeId.SIEGETANK: 0.5,
            UnitTypeId.MARINE: 1.5
        },
        UnitTypeId.GHOST: { # 3
            UnitTypeId.MARAUDER: 1.5
        },
        UnitTypeId.HELLION: { # 2
            UnitTypeId.MARAUDER: 1
        },
        UnitTypeId.LIBERATOR: { # 3
            UnitTypeId.VIKINGFIGHTER: 0.5
        },
        UnitTypeId.MARAUDER: { # 2
            UnitTypeId.MARINE: 1.6,
            UnitTypeId.BANSHEE: 0.3
        },
        UnitTypeId.MARINE: { # 1
            UnitTypeId.SIEGETANK: 0.15,
            UnitTypeId.MARINE: 0.5,
            UnitTypeId.WIDOWMINE: 0.1
        },
        UnitTypeId.MEDIVAC: { # 2
            UnitTypeId.VIKINGFIGHTER: 1
        },
        UnitTypeId.RAVEN: { # 2
            UnitTypeId.VIKINGFIGHTER: 0.5
        },
        UnitTypeId.REAPER: { # 1
            UnitTypeId.HELLION: 0.5,
            UnitTypeId.WIDOWMINE: 0.5
        },
        UnitTypeId.SIEGETANK: { # 3
            UnitTypeId.BANSHEE: 0.8
        },
        UnitTypeId.THOR: { # 6
            UnitTypeId.MARAUDER: 3
        },
        UnitTypeId.VIKINGFIGHTER: { # 2
            UnitTypeId.VIKINGFIGHTER: 1.15
        },
        UnitTypeId.WIDOWMINE: { # 2
            UnitTypeId.RAVEN: 0.4,
            UnitTypeId.MARAUDER: 0.8
        },
        # Zerg units
        UnitTypeId.BANELING: { # 0.5
            UnitTypeId.MARAUDER: 0.25,
            UnitTypeId.SIEGETANK: 0.1
        },
        UnitTypeId.BROODLORD: { # 2
            UnitTypeId.VIKINGFIGHTER: 1
        },
        UnitTypeId.CORRUPTOR: { # 2
            UnitTypeId.MARINE: 2.5,
        },
        UnitTypeId.HYDRALISK: { # 2
            UnitTypeId.SIEGETANK: 0.5,
            UnitTypeId.MARINE: 1
        },
        UnitTypeId.INFESTOR: { # 2
            UnitTypeId.GHOST: 0.5,
            UnitTypeId.SIEGETANK: 0.3
        },
        UnitTypeId.LURKERMP: { # 3
            UnitTypeId.RAVEN: 0.2,
            UnitTypeId.GHOST: 0.2,
            UnitTypeId.SIEGETANK: 0.2,
            UnitTypeId.BANSHEE: 0.5
        },
        UnitTypeId.MUTALISK: { # 2
            UnitTypeId.WIDOWMINE: 0.5,
            UnitTypeId.MARINE: 0.3,
            UnitTypeId.VIKINGFIGHTER: 0.3
        },
        UnitTypeId.OVERLORD: {
            UnitTypeId.VIKINGFIGHTER: 0.1
        },
        UnitTypeId.OVERSEER: {
            UnitTypeId.VIKINGFIGHTER: 0.2
        },
        UnitTypeId.QUEEN: { # 2
            UnitTypeId.MARINE: 2,
            UnitTypeId.SIEGETANK: 0.3
        },
        UnitTypeId.RAVAGER: { # 3
            UnitTypeId.MARAUDER: 0.5,
            UnitTypeId.MARINE: 1,
            UnitTypeId.BANSHEE: 0.5
        },
        UnitTypeId.ROACH: {
            UnitTypeId.MARAUDER: 0.75,
            UnitTypeId.BANSHEE: 0.5,
            UnitTypeId.SIEGETANK: 0.25,
            UnitTypeId.RAVEN: 0.1
        },
        UnitTypeId.SPINECRAWLER: { # 1
            UnitTypeId.SIEGETANK: 0.5,
        },
        UnitTypeId.SPIRE: { # 1
            UnitTypeId.VIKINGFIGHTER: 4,
        },
        UnitTypeId.SWARMHOSTMP: { # 3
            UnitTypeId.BANSHEE: 1
        },
        UnitTypeId.ULTRALISK: { # 6
            UnitTypeId.MARAUDER: 1,
            UnitTypeId.GHOST: 1.5
        },
        UnitTypeId.VIPER: { # 3
            UnitTypeId.VIKINGFIGHTER: 1
        },
        UnitTypeId.ZERGLING: {
            UnitTypeId.HELLION: 0.2,
            UnitTypeId.WIDOWMINE: 0.2,
            UnitTypeId.MARINE: 0.2
        },
    }

    @staticmethod
    def get_counters(enemy_units: Units) -> dict[UnitTypeId, float]:
        """Count the number of each unit type in the given units."""
        enemy_counts = UnitTypes.count_units_by_type(enemy_units)

        counter_units: dict[UnitTypeId, float] = {}
        for enemy_type, enemy_count in enemy_counts.items():
            if enemy_type in Counter.counters:
                unit_counters = Counter.counters[enemy_type]
                for counter_type, counter_count in unit_counters.items():
                    needed = counter_count * enemy_count
                    if counter_type in counter_units:
                        counter_units[counter_type] += needed
                    else:
                        counter_units[counter_type] = needed
        return counter_units

    # def get_counter(self, enemy_unit: Unit) -> dict[UnitTypeId, float]:
    #     """Count the number of each unit type in the given units."""
    #     if enemy_unit.type_id in Counter.counters:
    #         return Counter.counters[enemy_unit.type_id]
    #     return {}

    @staticmethod
    def get_counter_list(enemy_units: Units) -> List[UnitTypeId]:
        counter_units = Counter.get_counters(enemy_units)
        return [unit for unit, count in counter_units.items() for _ in range(math.ceil(count))]
