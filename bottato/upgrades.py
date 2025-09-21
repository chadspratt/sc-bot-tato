from loguru import logger

from typing import List

from sc2.bot_ai import BotAI
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.dicts.unit_research_abilities import RESEARCH_INFO


RESEARCH_ABILITIES: dict[UpgradeId, AbilityId] = {}

for builder_type, upgrades in RESEARCH_INFO.items():
    for upgrade_id, details in upgrades.items():
        RESEARCH_ABILITIES[upgrade_id] = details["ability"]


class Upgrades:
    # subset of UPGRADE_RESEARCHED_FROM
    infantry_types = [UnitTypeId.MARINE, UnitTypeId.REAPER, UnitTypeId.MARAUDER, UnitTypeId.GHOST]
    vehicle_types = [UnitTypeId.HELLION, UnitTypeId.SIEGETANK, UnitTypeId.CYCLONE, UnitTypeId.HELLIONTANK, UnitTypeId.THOR]
    ship_types = [UnitTypeId.VIKINGFIGHTER, UnitTypeId.BANSHEE, UnitTypeId.LIBERATOR, UnitTypeId.BATTLECRUISER]

    affected_unit_types: dict[UpgradeId, list[UnitTypeId]] = {
        # ==barracks techlab==
        # concussive shells
        UpgradeId.PUNISHERGRENADES: [UnitTypeId.MARAUDER],
        # combat shield
        UpgradeId.SHIELDWALL: [UnitTypeId.MARINE],
        UpgradeId.STIMPACK: [UnitTypeId.MARINE, UnitTypeId.MARAUDER],
        # ==factory techlab==
        UpgradeId.HURRICANETHRUSTERS: [UnitTypeId.CYCLONE],
        UpgradeId.DRILLCLAWS: [UnitTypeId.WIDOWMINE],
        # blue flame
        UpgradeId.HIGHCAPACITYBARRELS: [UnitTypeId.HELLION],
        UpgradeId.SMARTSERVOS: [UnitTypeId.HELLION, UnitTypeId.HELLIONTANK, UnitTypeId.VIKINGFIGHTER, UnitTypeId.THOR],
        # ==starport techlab==
        UpgradeId.BANSHEECLOAK: [UnitTypeId.BANSHEE],
        UpgradeId.BANSHEESPEED: [UnitTypeId.BANSHEE],
        # ==engineering bay==
        UpgradeId.HISECAUTOTRACKING: [UnitTypeId.RAVEN, UnitTypeId.MISSILETURRET, UnitTypeId.PLANETARYFORTRESS],
        UpgradeId.TERRANBUILDINGARMOR: [],
        UpgradeId.TERRANINFANTRYARMORSLEVEL1: infantry_types,
        UpgradeId.TERRANINFANTRYARMORSLEVEL2: infantry_types,
        UpgradeId.TERRANINFANTRYARMORSLEVEL3: infantry_types,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL1: infantry_types,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL2: infantry_types,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL3: infantry_types,
        # ==armory==
        UpgradeId.TERRANSHIPWEAPONSLEVEL1: ship_types,
        UpgradeId.TERRANSHIPWEAPONSLEVEL2: ship_types,
        UpgradeId.TERRANSHIPWEAPONSLEVEL3: ship_types,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1: vehicle_types + ship_types,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2: vehicle_types + ship_types,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3: vehicle_types + ship_types,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL1: vehicle_types,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL2: vehicle_types,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL3: vehicle_types,
        # ==fusion core==
        UpgradeId.BATTLECRUISERENABLESPECIALIZATIONS: [UnitTypeId.BATTLECRUISER],
        UpgradeId.LIBERATORAGRANGEUPGRADE: [UnitTypeId.LIBERATOR],
        UpgradeId.MEDIVACINCREASESPEEDBOOST: [UnitTypeId.MEDIVAC],
        # ==ghost academy==
        UpgradeId.PERSONALCLOAKING: [UnitTypeId.GHOST],
    }
    # upgrade_order: list[UpgradeId] = [
    #     UpgradeId.SHIELDWALL,  # barracks
    #     UpgradeId.HURRICANETHRUSTERS,  # factory
    #     UpgradeId.BANSHEESPEED,  # starport
    #     UpgradeId.HISECAUTOTRACKING,  # ebay
    #     UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,  # armory
    #     UpgradeId.STIMPACK,  # barracks
    #     UpgradeId.HIGHCAPACITYBARRELS,  # factory
    #     UpgradeId.BANSHEECLOAK,  # starport
    #     UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,  # ebay
    #     UpgradeId.TERRANSHIPWEAPONSLEVEL1,  # armory
    #     UpgradeId.PUNISHERGRENADES,  # barracks
    #     UpgradeId.SMARTSERVOS,  # broken
    #     UpgradeId.TERRANINFANTRYARMORSLEVEL1,  # ebay
    #     UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1,  # armory, broken
    #     UpgradeId.TERRANBUILDINGARMOR,  # ebay
    #     UpgradeId.TERRANINFANTRYWEAPONSLEVEL2,  # ebay
    #     UpgradeId.TERRANINFANTRYARMORSLEVEL2,  # ebay
    #     UpgradeId.TERRANSHIPWEAPONSLEVEL2,  # armory
    #     UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,  # armory
    #     UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2,  # armory, broken
    #     UpgradeId.TERRANINFANTRYWEAPONSLEVEL3,  # ebay
    #     UpgradeId.TERRANINFANTRYARMORSLEVEL3,  # ebay
    #     UpgradeId.TERRANSHIPWEAPONSLEVEL3,  # armory
    #     UpgradeId.TERRANVEHICLEWEAPONSLEVEL3,  # armory
    #     UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3,  # armory, broken
    #     UpgradeId.DRILLCLAWS,  # factory
    # ]
    upgrades_by_facility: dict[UnitTypeId, list[UpgradeId]] = {
        UnitTypeId.BARRACKSTECHLAB: [
            UpgradeId.SHIELDWALL,
            UpgradeId.STIMPACK,
            UpgradeId.PUNISHERGRENADES,
        ],
        UnitTypeId.FACTORYTECHLAB: [
            # UpgradeId.HURRICANETHRUSTERS,
            # UpgradeId.HIGHCAPACITYBARRELS,
            # UpgradeId.SMARTSERVOS,
            # UpgradeId.DRILLCLAWS,
        ],
        UnitTypeId.STARPORTTECHLAB: [
            UpgradeId.BANSHEECLOAK,
            UpgradeId.BANSHEESPEED,
            # UpgradeId.INTERFERENCEMATRIX,
        ],
        UnitTypeId.ARMORY: [
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1,
            UpgradeId.TERRANSHIPWEAPONSLEVEL1,
            UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2,
            UpgradeId.TERRANSHIPWEAPONSLEVEL2,
            UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3,
            UpgradeId.TERRANSHIPWEAPONSLEVEL3,
            UpgradeId.TERRANVEHICLEWEAPONSLEVEL3,
        ],
        UnitTypeId.ENGINEERINGBAY: [
            UpgradeId.HISECAUTOTRACKING,
            UpgradeId.TERRANBUILDINGARMOR,
            UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
            UpgradeId.TERRANINFANTRYARMORSLEVEL1,
            UpgradeId.TERRANINFANTRYWEAPONSLEVEL2,
            UpgradeId.TERRANINFANTRYARMORSLEVEL2,
            UpgradeId.TERRANINFANTRYWEAPONSLEVEL3,
            UpgradeId.TERRANINFANTRYARMORSLEVEL3,
        ],
        UnitTypeId.FUSIONCORE: [
            UpgradeId.BATTLECRUISERENABLESPECIALIZATIONS,
            UpgradeId.MEDIVACCADUCEUSREACTOR,
            UpgradeId.LIBERATORAGRANGEUPGRADE,
        ],
        UnitTypeId.GHOSTACADEMY: [
            UpgradeId.PERSONALCLOAKING,
        ],
    }

    def __init__(self, bot: BotAI) -> None:
        logger.debug("created upgrades manager")
        self.bot = bot
        self.index = 0

    def get_upgrades(self) -> List[UpgradeId]:
        return (
            self.next_upgrades(UnitTypeId.ARMORY)
            + self.next_upgrades(UnitTypeId.ENGINEERINGBAY)
            + self.next_upgrades(UnitTypeId.BARRACKSTECHLAB)
            + self.next_upgrades(UnitTypeId.FACTORYTECHLAB)
            + self.next_upgrades(UnitTypeId.STARPORTTECHLAB)
            # + self.next_upgrades(UnitTypeId.FUSIONCORE)
            # + self.next_upgrades(UnitTypeId.GHOSTACADEMY)
        )

    def next_upgrades(self, facility_type: UnitTypeId) -> List[UpgradeId]:
        new_upgrades = []
        number_needed: int = len(self.bot.structures(facility_type).idle)
        if number_needed > 0:
            for upgrade_type in self.upgrades_by_facility[facility_type]:
                upgrade_progress = self.bot.already_pending_upgrade(upgrade_type)
                logger.debug(f"upgrade progress {upgrade_type}: {upgrade_progress}")
                if upgrade_progress > 0:
                    continue
                new_upgrades.append(upgrade_type)
                if len(new_upgrades) == number_needed:
                    break
        return new_upgrades
