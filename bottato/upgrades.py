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
    vehicle_types = [UnitTypeId.HELLION, UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED, UnitTypeId.CYCLONE, UnitTypeId.HELLIONTANK, UnitTypeId.THOR]
    ship_types = [UnitTypeId.VIKINGFIGHTER, UnitTypeId.BANSHEE, UnitTypeId.LIBERATOR, UnitTypeId.BATTLECRUISER]

    affected_unit_types: dict[UpgradeId, list[UnitTypeId]] = {
        # ==barracks techlab==
        # concussive shells
        UpgradeId.PUNISHERGRENADES: [UnitTypeId.MARAUDER],
        # combat shield
        UpgradeId.SHIELDWALL: [UnitTypeId.MARINE],
        UpgradeId.STIMPACK: [UnitTypeId.MARINE, UnitTypeId.MARAUDER],
        # ==factory techlab==
        UpgradeId.CYCLONELOCKONDAMAGEUPGRADE: [UnitTypeId.CYCLONE],
        UpgradeId.DRILLCLAWS: [UnitTypeId.WIDOWMINE],
        # blue flame
        UpgradeId.HIGHCAPACITYBARRELS: [UnitTypeId.HELLION],
        UpgradeId.SMARTSERVOS: [UnitTypeId.HELLION, UnitTypeId.HELLIONTANK, UnitTypeId.VIKINGFIGHTER, UnitTypeId.THOR],
        # ==starport techlab==
        UpgradeId.BANSHEECLOAK: [UnitTypeId.BANSHEE],
        UpgradeId.BANSHEESPEED: [UnitTypeId.BANSHEE],
        # ==engineering bay==
        UpgradeId.HISECAUTOTRACKING: [UnitTypeId.RAVEN, UnitTypeId.MISSILETURRET, UnitTypeId.PLANETARYFORTRESS],
        UpgradeId.TERRANBUILDINGARMOR: [UnitTypeId.BARRACKS],
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
    
    upgrades_by_facility: dict[UnitTypeId, list[UpgradeId]] = {
        UnitTypeId.BARRACKSTECHLAB: [
            UpgradeId.STIMPACK,
            UpgradeId.SHIELDWALL,
            UpgradeId.PUNISHERGRENADES,
        ],
        UnitTypeId.FACTORYTECHLAB: [
            UpgradeId.HIGHCAPACITYBARRELS,
            UpgradeId.CYCLONELOCKONDAMAGEUPGRADE,
            UpgradeId.SMARTSERVOS,
            UpgradeId.DRILLCLAWS,
        ],
        UnitTypeId.STARPORTTECHLAB: [
            UpgradeId.BANSHEECLOAK,
            UpgradeId.BANSHEESPEED,
            # UpgradeId.INTERFERENCEMATRIX,
        ],
        UnitTypeId.ARMORY: [
            UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1,
            UpgradeId.TERRANSHIPWEAPONSLEVEL1,
            UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2,
            UpgradeId.TERRANSHIPWEAPONSLEVEL2,
            UpgradeId.TERRANVEHICLEWEAPONSLEVEL3,
            UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3,
            UpgradeId.TERRANSHIPWEAPONSLEVEL3,
        ],
        UnitTypeId.ENGINEERINGBAY: [
            UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
            UpgradeId.TERRANINFANTRYARMORSLEVEL1,
            UpgradeId.TERRANINFANTRYWEAPONSLEVEL2,
            UpgradeId.TERRANINFANTRYARMORSLEVEL2,
            UpgradeId.HISECAUTOTRACKING,
            UpgradeId.TERRANBUILDINGARMOR,
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

    prereqs: dict[UpgradeId, UpgradeId | None] = {
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL2: UpgradeId.TERRANINFANTRYWEAPONSLEVEL1,
        UpgradeId.TERRANINFANTRYWEAPONSLEVEL3: UpgradeId.TERRANINFANTRYWEAPONSLEVEL2,
        UpgradeId.TERRANINFANTRYARMORSLEVEL2: UpgradeId.TERRANINFANTRYARMORSLEVEL1,
        UpgradeId.TERRANINFANTRYARMORSLEVEL3: UpgradeId.TERRANINFANTRYARMORSLEVEL2,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL2: UpgradeId.TERRANVEHICLEWEAPONSLEVEL1,
        UpgradeId.TERRANVEHICLEWEAPONSLEVEL3: UpgradeId.TERRANVEHICLEWEAPONSLEVEL2,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2: UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1,
        UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3: UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2,
        UpgradeId.TERRANSHIPWEAPONSLEVEL2: UpgradeId.TERRANSHIPWEAPONSLEVEL1,
        UpgradeId.TERRANSHIPWEAPONSLEVEL3: UpgradeId.TERRANSHIPWEAPONSLEVEL2,
    }

    def __init__(self, bot: BotAI) -> None:
        logger.debug("created upgrades manager")
        self.bot = bot
        self.index = 0
    
    def next_upgrade(self, facility_type: UnitTypeId) -> UpgradeId | None:
        for upgrade_type in self.upgrades_by_facility[facility_type]:
            if upgrade_type != UpgradeId.TERRANBUILDINGARMOR and not self.bot.units(self.affected_unit_types[upgrade_type]):
                # don't research if no units benefit
                continue
            if self.already_pending_upgrade(facility_type, upgrade_type) > 0:
                continue
            if upgrade_type in self.prereqs and self.already_pending_upgrade(facility_type, self.prereqs[upgrade_type]) != 1:
                continue
            return upgrade_type
        return None
    
    # patched version of python-sc2 which has wrong ability ids for some upgrades
    def already_pending_upgrade(self, facility_type: UnitTypeId, upgrade_type: UpgradeId) -> float:
        assert isinstance(upgrade_type, UpgradeId), f"{upgrade_type} is no UpgradeId"
        if upgrade_type in self.bot.state.upgrades:
            return 1
        creationAbilityID = self.bot.game_data.upgrades[upgrade_type.value].research_ability.exact_id
        if upgrade_type == UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL1:
            creationAbilityID = AbilityId.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL1
        elif upgrade_type == UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL2:
            creationAbilityID = AbilityId.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL2
        elif upgrade_type == UpgradeId.TERRANVEHICLEANDSHIPARMORSLEVEL3:
            creationAbilityID = AbilityId.ARMORYRESEARCH_TERRANVEHICLEANDSHIPPLATINGLEVEL3
        elif upgrade_type == UpgradeId.INTERFERENCEMATRIX:
            creationAbilityID = AbilityId.STARPORTTECHLABRESEARCH_RESEARCHRAVENINTERFERENCEMATRIX
        for structure in self.bot.structures.filter(lambda unit: unit.type_id == facility_type and unit.is_ready):
            for order in structure.orders:
                if order.ability.exact_id == creationAbilityID:
                    return order.progress
        return 0
