import enum
from sc2.dicts.unit_unit_alias import UNIT_UNIT_ALIAS
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit



class UnitAttribute(enum.Enum):
    """
    Unit attributes for SC2 units.
    """

    LIGHT = 0
    BIOLOGICAL = 1
    PSIONIC = 2
    MASSIVE = 3
    MECHANICAL = 4
    ARMORED = 5
    HEROIC = 6
    DETECTOR = 7
    STRUCTURE = 8


class UnitTypes():
    PROTOSS = {
        UnitTypeId.ADEPT: {
            "supply": 2,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.BIOLOGICAL),
            "bonus_against": (UnitAttribute.LIGHT,),
        },
        UnitTypeId.ARCHON: {
            "supply": 4,
            "attributes": (UnitAttribute.PSIONIC, UnitAttribute.MASSIVE),
            "bonus_against": (UnitAttribute.BIOLOGICAL,),
        },
        UnitTypeId.CARRIER: {
            "supply": 6,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MASSIVE, UnitAttribute.MECHANICAL),
        },
        UnitTypeId.COLOSSUS: {
            "supply": 6,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MASSIVE, UnitAttribute.MECHANICAL),
            "bonus_against": (UnitAttribute.LIGHT,),
        },
        UnitTypeId.DARKTEMPLAR: {
            "supply": 2,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT, UnitAttribute.PSIONIC),
        },
        UnitTypeId.DISRUPTOR: {
            "supply": 4,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL),
        },
        UnitTypeId.HIGHTEMPLAR: {
            "supply": 2,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT, UnitAttribute.PSIONIC),
        },
        UnitTypeId.IMMORTAL: {
            "supply": 4,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL),
            "bonus_against": (UnitAttribute.ARMORED,),
        },
        UnitTypeId.INTERCEPTOR: {
            "supply": 0,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.MECHANICAL),
        },
        UnitTypeId.MOTHERSHIP: {
            "supply": 8,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MASSIVE, UnitAttribute.PSIONIC, UnitAttribute.MECHANICAL, UnitAttribute.HEROIC),
        },
        UnitTypeId.OBSERVER: {
            "supply": 1,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.MECHANICAL, UnitAttribute.DETECTOR),
        },
        UnitTypeId.ORACLE: {
            "supply": 3,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL, UnitAttribute.PSIONIC),
            "bonus_against": (UnitAttribute.LIGHT,),
        },
        UnitTypeId.PHOENIX: {
            "supply": 2,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.MECHANICAL),
            "bonus_against": (UnitAttribute.LIGHT,),
        },
        UnitTypeId.PROBE: {
            "supply": 1,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.MECHANICAL),
        },
        UnitTypeId.SENTRY: {
            "supply": 2,
            "attributes": (UnitAttribute.MECHANICAL, UnitAttribute.PSIONIC),
        },
        UnitTypeId.STALKER: {
            "supply": 2,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL),
            "bonus_against": (UnitAttribute.ARMORED,),
        },
        UnitTypeId.TEMPEST: {
            "supply": 4,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL, UnitAttribute.MASSIVE),
            "bonus_against": (UnitAttribute.MASSIVE, UnitAttribute.STRUCTURE),
        },
        UnitTypeId.VOIDRAY: {
            "supply": 4,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL),
            "bonus_against": (UnitAttribute.ARMORED,),
        },
        UnitTypeId.WARPPRISM: {
            "supply": 2,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL, UnitAttribute.PSIONIC),
        },
        UnitTypeId.ZEALOT: {
            "supply": 2,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
        },
    }
    TERRAN = {
        UnitTypeId.BANSHEE: {
            "supply": 3,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.MECHANICAL),
            "tech level": 2,
        },
        UnitTypeId.BATTLECRUISER: {
            "supply": 6,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL, UnitAttribute.MASSIVE),
            "tech level": 3,
        },
        UnitTypeId.CYCLONE: {
            "supply": 3,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL),
            "tech level": 2,
        },
        UnitTypeId.GHOST: {
            "supply": 3,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.PSIONIC),
            "bonus_against": (UnitAttribute.LIGHT,),
            "tech level": 3,
        },
        UnitTypeId.HELLION: {
            "supply": 2,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.MECHANICAL),
            "bonus_against": (UnitAttribute.LIGHT,),
            "tech level": 1,
        },
        UnitTypeId.HELLIONTANK: {
            "supply": 2,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT, UnitAttribute.MECHANICAL),
            "bonus_against": (UnitAttribute.LIGHT,),
            "tech level": 2,
        },
        UnitTypeId.LIBERATOR: {
            "supply": 3,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL),
            "tech level": 2,
        },
        UnitTypeId.MARAUDER: {
            "supply": 2,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.BIOLOGICAL),
            "bonus_against": (UnitAttribute.ARMORED,),
            "tech level": 2,
        },
        UnitTypeId.MARINE: {
            "supply": 1,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
            "tech level": 1,
        },
        UnitTypeId.MEDIVAC: {
            "supply": 2,
            "attributes": (UnitAttribute.MECHANICAL, UnitAttribute.ARMORED),
            "tech level": 1,
        },
        UnitTypeId.RAVEN: {
            "supply": 2,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.MECHANICAL, UnitAttribute.DETECTOR),
            "tech level": 2,
        },
        UnitTypeId.REAPER: {
            "supply": 1,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
            "tech level": 1,
        },
        UnitTypeId.SCV: {
            "supply": 1,
            "attributes": (UnitAttribute.LIGHT, UnitAttribute.MECHANICAL, UnitAttribute.BIOLOGICAL),
            "tech level": 0,
        },
        UnitTypeId.SIEGETANK: {
            "supply": 3,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL),
            "bonus_against": (UnitAttribute.ARMORED,),
            "tech level": 1,
        },
        UnitTypeId.THOR: {
            "supply": 6,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL, UnitAttribute.MASSIVE),
            "bonus_against": (UnitAttribute.MASSIVE, UnitAttribute.LIGHT),
            "tech level": 3,
        },
        UnitTypeId.VIKINGFIGHTER: {
            "supply": 2,
            "attributes": (UnitAttribute.MECHANICAL, UnitAttribute.ARMORED),
            "bonus_against": (UnitAttribute.ARMORED, UnitAttribute.MECHANICAL),
            "tech level": 1,
        },
        UnitTypeId.WIDOWMINE: {
            "supply": 2,
            "attributes": (UnitAttribute.MECHANICAL, UnitAttribute.LIGHT),
            "tech level": 2,
        },
    }
    ZERG = {
        UnitTypeId.BANELING: {
            "supply": 0.5,
            "attributes": (UnitAttribute.BIOLOGICAL,),
            "bonus_against": (UnitAttribute.LIGHT,),
        },
        UnitTypeId.BROODLORD: {
            "supply": 2,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.BIOLOGICAL, UnitAttribute.MASSIVE),
        },
        UnitTypeId.BROODLING: {
            "supply": 0,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
        },
        UnitTypeId.CHANGELING: {
            "supply": 0,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
        },
        UnitTypeId.CORRUPTOR: {
            "supply": 2,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.BIOLOGICAL),
            "bonus_against": (UnitAttribute.MASSIVE,),
        },
        UnitTypeId.DRONE: {
            "supply": 1,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
        },
        UnitTypeId.HYDRALISK: {
            "supply": 2,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
        },
        UnitTypeId.INFESTOR: {
            "supply": 2,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.PSIONIC, UnitAttribute.ARMORED),
        },
        UnitTypeId.LOCUSTMP: {
            "supply": 0,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
        },
        UnitTypeId.LURKERMP: {
            "supply": 1,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.BIOLOGICAL),
            "bonus_against": (UnitAttribute.ARMORED,),
        },
        UnitTypeId.MUTALISK: {
            "supply": 2,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
        },
        UnitTypeId.NYDUSCANAL: {
            "supply": 0,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.ARMORED, UnitAttribute.STRUCTURE),
        },
        UnitTypeId.OVERLORD: {
            "supply": 0,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.ARMORED),
        },
        UnitTypeId.OVERSEER: {
            "supply": 0,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.DETECTOR, UnitAttribute.ARMORED),
        },
        UnitTypeId.QUEEN: {
            "supply": 2,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.PSIONIC),
        },
        UnitTypeId.RAVAGER: {
            "supply": 3,
            "attributes": (UnitAttribute.BIOLOGICAL,),
        },
        UnitTypeId.ROACH: {
            "supply": 2,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.BIOLOGICAL),
        },
        UnitTypeId.SWARMHOSTMP: {
            "supply": 3,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.BIOLOGICAL),
        },
        UnitTypeId.ULTRALISK: {
            "supply": 6,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.BIOLOGICAL, UnitAttribute.MASSIVE),
        },
        UnitTypeId.VIPER: {
            "supply": 3,
            "attributes": (UnitAttribute.ARMORED, UnitAttribute.BIOLOGICAL, UnitAttribute.PSIONIC),
        },
        UnitTypeId.ZERGLING: {
            "supply": 0.5,
            "attributes": (UnitAttribute.BIOLOGICAL, UnitAttribute.LIGHT),
        },
    }

    GOOD_AGAINST = {
        UnitAttribute.ARMORED: {
            "PROTOSS": (UnitTypeId.IMMORTAL, UnitTypeId.STALKER, UnitTypeId.VOIDRAY),
            "TERRAN": (UnitTypeId.MARAUDER, UnitTypeId.SIEGETANK, UnitTypeId.VIKINGFIGHTER),
            "ZERG": (UnitTypeId.LURKERMP,),
        },
        UnitAttribute.BIOLOGICAL: {
            "PROTOSS": (UnitTypeId.ARCHON,),
            "TERRAN": (),
            "ZERG": (),
        },
        UnitAttribute.MASSIVE: {
            "PROTOSS": (UnitTypeId.TEMPEST,),
            "TERRAN": (UnitTypeId.THOR,),
            "ZERG": (UnitTypeId.CORRUPTOR,),
        },
        UnitAttribute.MECHANICAL: {
            "PROTOSS": (),
            "TERRAN": (UnitTypeId.VIKINGFIGHTER,),
            "ZERG": (),
        },
        UnitAttribute.LIGHT: {
            "PROTOSS": (UnitTypeId.ADEPT, UnitTypeId.COLOSSUS, UnitTypeId.ORACLE, UnitTypeId.PHOENIX),
            "TERRAN": (UnitTypeId.GHOST, UnitTypeId.HELLION, UnitTypeId.HELLIONTANK, UnitTypeId.THOR),
            "ZERG": (UnitTypeId.BANELING,),
        },
        UnitAttribute.STRUCTURE: {
            "PROTOSS": (UnitTypeId.TEMPEST,),
            "TERRAN": (),
            "ZERG": (),
        },
    }

    def get_unit_info(self, unit_type_id: UnitTypeId) -> dict:
        """
        Get the unit info for a given unit type ID.
        """
        common_id = UNIT_UNIT_ALIAS.get(unit_type_id, unit_type_id)
        if common_id in self.PROTOSS:
            return self.PROTOSS[common_id]
        elif common_id in self.TERRAN:
            return self.TERRAN[common_id]
        elif common_id in self.ZERG:
            return self.ZERG[common_id]
        else:
            return None
        
    def can_attack_air(unit: Unit) -> bool:
        """
        Check if a unit type can attack air units.
        """
        return unit.can_attack_air or unit.type_id in {UnitTypeId.SENTRY, UnitTypeId.BATTLECRUISER, UnitTypeId.VOIDRAY}
    
    def can_attack_ground(unit: Unit) -> bool:
        """
        Check if a unit type can attack air units.
        """
        return unit.can_attack_ground or unit.type_id in {UnitTypeId.SENTRY, UnitTypeId.BATTLECRUISER, UnitTypeId.VOIDRAY, UnitTypeId.BANELING}

    def can_attack(unit: Unit) -> bool:
        """
        Check if a unit type can attack (either air or ground).
        """
        return UnitTypes.can_attack_air(unit) or UnitTypes.can_attack_ground(unit)

    def ground_range(unit: Unit) -> float:
        """
        Get the ground attack range of a unit type.
        """
        if unit.can_attack_ground:
            return unit.ground_range
        elif unit.type_id == UnitTypeId.SENTRY:
            return 5.0
        elif unit.type_id in {UnitTypeId.BATTLECRUISER, UnitTypeId.VOIDRAY}:
            return 6.0
        elif unit.type_id == UnitTypeId.BANELING:
            return 1.0  # Banelings have melee range
        else:
            return 0.0
        
    def air_range(unit: Unit) -> float:
        """
        Get the air attack range of a unit type.
        """
        if unit.can_attack_air:
            return unit.air_range
        elif unit.type_id == UnitTypeId.SENTRY:
            return 5.0
        elif unit.type_id in {UnitTypeId.BATTLECRUISER, UnitTypeId.VOIDRAY}:
            return 6.0
        else:
            return 0.0