from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.upgrade_id import UpgradeId
from sc2.ids.unit_typeid import UnitTypeId


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
        # UpgradeId.CYCLONELOCKONDAMAGEUPGRADE: [UnitTypeId.CYCLONE],
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
    upgrade_order: list[UpgradeId] = [
        UpgradeId.TERRANSHIPWEAPONSLEVEL1,  # armory
        UpgradeId.SHIELDWALL,  # barracks
        UpgradeId.HISECAUTOTRACKING,  # ebay
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,  # armory
        UpgradeId.BANSHEESPEED,  # starport
        UpgradeId.HURRICANETHRUSTERS,  # factory
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,  # ebay
        UpgradeId.TERRANINFANTRYARMORSLEVEL1,  # ebay
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1,  # armory
        UpgradeId.TERRANBUILDINGARMOR,  # ebay
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL2,  # ebay
        UpgradeId.TERRANINFANTRYARMORSLEVEL2,  # ebay
        UpgradeId.TERRANSHIPWEAPONSLEVEL2,  # armory
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,  # armory
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2,  # armory
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL3,  # ebay
        UpgradeId.TERRANINFANTRYARMORSLEVEL3,  # ebay
        UpgradeId.TERRANSHIPWEAPONSLEVEL3,  # armory
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL3,  # armory
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3,  # armory
        # UpgradeId.STIMPACK,  # barracks
        # UpgradeId.BANSHEECLOAK,  # starport
    ]

    def __init__(self, bot: BotAI) -> None:
        logger.info("created upgrades manager")
        self.bot = bot
        self.index = 0

    def next_upgrade(self) -> UpgradeId:
        # check if last upgrade is finished
        for upgrade_type in self.upgrade_order:
            if self.bot.already_pending_upgrade(upgrade_type):
                continue
            return upgrade_type
