from typing import Any, Dict, List, Tuple

from sc2.bot_ai import BotAI
from sc2.dicts.unit_unit_alias import UNIT_UNIT_ALIAS
from sc2.ids.effect_id import EffectId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.enums import UnitAttribute
from bottato.mixins import GeometryMixin, timed


class UnitTypes(GeometryMixin):
    PROTOSS: Dict[UnitTypeId, Dict[str, Any]] = {
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
    TERRAN: Dict[UnitTypeId, Dict[str, Any]] = {
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
    ZERG: Dict[UnitTypeId, Dict[str, Any]] = {
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

    GOOD_AGAINST: Dict[UnitAttribute, Dict[str, Tuple[UnitTypeId, ...]]] = {
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

    ZERG_STRUCTURES_THAT_DONT_SPAWN_BROODLINGS = {
        UnitTypeId.SPORECRAWLER,
        UnitTypeId.SPINECRAWLER,
        UnitTypeId.EXTRACTOR,
        UnitTypeId.CREEPTUMOR,
        UnitTypeId.CREEPTUMORBURROWED,
        UnitTypeId.CREEPTUMORQUEEN,
    }

    HIGH_PRIORITY_TARGETS = {
        UnitTypeId.SIEGETANK,
        UnitTypeId.SIEGETANKSIEGED,
        UnitTypeId.INFESTOR,
        UnitTypeId.HIGHTEMPLAR,
        UnitTypeId.LURKERMP,
    }

    OFFENSIVE_STRUCTURE_TYPES = (
        UnitTypeId.BUNKER,
        UnitTypeId.PHOTONCANNON,
        UnitTypeId.MISSILETURRET,
        UnitTypeId.SPINECRAWLER,
        UnitTypeId.SPORECRAWLER,
        UnitTypeId.PLANETARYFORTRESS,
    )

    ANTI_AIR_STRUCTURE_TYPES = (
        UnitTypeId.MISSILETURRET,
        UnitTypeId.SPORECRAWLER,
        UnitTypeId.PHOTONCANNON,
    )

    WORKER_TYPES = [
        UnitTypeId.DRONE,
        UnitTypeId.DRONEBURROWED,
        UnitTypeId.PROBE,
        UnitTypeId.SCV,
        UnitTypeId.MULE,
    ]

    NON_THREATS = [
        UnitTypeId.LARVA,
        UnitTypeId.EGG,
        UnitTypeId.OVERLORD,
        UnitTypeId.OVERSEER,
        UnitTypeId.CHANGELING,
        UnitTypeId.DRONE,
        UnitTypeId.DRONEBURROWED,
        UnitTypeId.PROBE,
        UnitTypeId.SCV,
        UnitTypeId.MULE,
        UnitTypeId.ADEPTPHASESHIFT,
    ]

    NON_THREAT_DETECTORS = [
        UnitTypeId.OVERSEER,
        UnitTypeId.RAVEN,
        UnitTypeId.OBSERVER,
    ]

    @staticmethod
    def is_worker(unit_type_id: UnitTypeId) -> bool:
        """
        Check if a unit type ID is a worker.
        """
        common_id = UNIT_UNIT_ALIAS.get(unit_type_id, unit_type_id)
        return common_id in UnitTypes.WORKER_TYPES

    def get_unit_info(self, unit_type_id: UnitTypeId) -> Dict[str, Any]:
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
            return {
                "supply": 0,
                "attributes": (UnitAttribute.STRUCTURE,),
            }
        
    @staticmethod
    def can_attack_air(unit: Unit) -> bool:
        """
        Check if a unit type can attack air units.
        """
        return unit.can_attack_air or unit.type_id in {
            UnitTypeId.BUNKER,
            UnitTypeId.BATTLECRUISER, 
            UnitTypeId.SENTRY, 
            UnitTypeId.VOIDRAY, 
            UnitTypeId.WIDOWMINE,
        }
    
    @staticmethod
    def can_attack_ground(unit: Unit) -> bool:
        """
        Check if a unit type can attack air units.
        """
        return unit.can_attack_ground or unit.type_id in {
            UnitTypeId.BANELING,
            UnitTypeId.BATTLECRUISER,
            UnitTypeId.BUNKER,
            UnitTypeId.SENTRY,
            UnitTypeId.VOIDRAY,
            UnitTypeId.WIDOWMINE,
        }

    @staticmethod
    def can_attack(unit: Unit) -> bool:
        """
        Check if a unit type can attack (either air or ground).
        """
        return UnitTypes.can_attack_air(unit) or UnitTypes.can_attack_ground(unit)

    @staticmethod
    def ground_range(unit: Unit) -> float:
        """
        Get the ground attack range of a unit type.
        """
        if unit.can_attack_ground:
            return unit.ground_range
        elif unit.type_id in {UnitTypeId.SENTRY, UnitTypeId.WIDOWMINE, UnitTypeId.WIDOWMINEBURROWED}:
            return 5.0
        elif unit.type_id in {UnitTypeId.BATTLECRUISER, UnitTypeId.VOIDRAY}:
            return 6.0
        elif unit.type_id == UnitTypeId.BANELING:
            return 1.0  # Banelings have melee range
        else:
            return 0.0
        
    @staticmethod
    def air_range(unit: Unit) -> float:
        """
        Get the air attack range of a unit type.
        """
        if unit.can_attack_air:
            return unit.air_range
        elif unit.type_id in {UnitTypeId.SENTRY, UnitTypeId.WIDOWMINE, UnitTypeId.WIDOWMINEBURROWED}:
            return 5.0
        elif unit.type_id in {UnitTypeId.BATTLECRUISER, UnitTypeId.VOIDRAY}:
            return 6.0
        else:
            return 0.0
        
    @staticmethod
    def range(unit: Unit) -> float:
        """
        Get the maximum attack range of a unit type (either air or ground).
        """
        return max(UnitTypes.ground_range(unit), UnitTypes.air_range(unit))
        
    @staticmethod
    @timed
    def dps(attacker: Unit, target: Unit) -> float:
        """
        Get the DPS of the attacker unit against the target unit.
        """
        try:
            if not UnitTypes.can_attack_target(attacker, target):
                return 0.0
        except AttributeError:
            return 0.0
        if attacker.type_id == UnitTypeId.VOIDRAY:
            return 16.8
        if attacker.type_id == UnitTypeId.ORACLE:
            return 24.4
        if attacker.type_id == UnitTypeId.BATTLECRUISER:
            return 49.8
        if attacker.type_id == UnitTypeId.SENTRY:
            return 8.4
        if attacker.type_id == UnitTypeId.WIDOWMINE:
            return 15.0
        if attacker.type_id == UnitTypeId.WIDOWMINEBURROWED:
            return 30.0
        return attacker.calculate_dps_vs_target(target)
        
    @staticmethod
    def target_in_range(attacker: Unit, target: Unit, bonus_distance: float = 0.0) -> bool:
        """
        Check if a target unit is in range of the given unit, considering both air and ground attacks.
        """
        if not attacker.is_ready:
            return False
        attack_range = UnitTypes.range_vs_target(attacker, target)
        if attack_range == 0.0:
            return False
        distance = UnitTypes.distance_squared(attacker, target)
        return distance <= (attacker.radius + target.radius + attack_range + bonus_distance) ** 2
    
    @staticmethod
    def get_range_buffer_vs_target(attacker: Unit, target: Unit, attacker_position: Point2 | None = None, target_position: Point2 | None = None) -> float:
        """
        Get the range buffer of the attacker unit against the target unit.
        """
        attack_range = UnitTypes.range_vs_target(attacker, target)
        if attack_range == 0.0:
            return float('inf')
        distance = UnitTypes.distance_squared(attacker_position if attacker_position else attacker, target_position if target_position else target)
        if distance > 500:
            # too far away to care
            return float('inf')
        actual_distance = (distance ** 0.5) - attacker.radius - target.radius
        return actual_distance - attack_range
    
    @staticmethod
    def range_vs_target(attacker: Unit, target: Unit) -> float:
        """
        Get the attack range of the attacker unit against the target unit.
        """
        if attacker.type_id == UnitTypeId.HIGHTEMPLAR and target.energy > 10:
            return 10 # feedback
        if target.is_cloaked and attacker.is_detector:
            return attacker.sight_range # treat detection as a weapon to be avoided
        if target.is_flying:
            return UnitTypes.air_range(attacker)
        if attacker.type_id == UnitTypeId.BUNKER:
            return 6
        elif target.type_id == UnitTypeId.COLOSSUS:
            return max(UnitTypes.ground_range(attacker), UnitTypes.air_range(attacker))
        else:
            return UnitTypes.ground_range(attacker)
        
    @staticmethod
    def can_attack_target(attacker: Unit, target: Unit) -> bool:
        """
        Check if the attacker unit can attack the target unit.
        """
        if not attacker.is_ready and attacker.type_id != UnitTypeId.OBSERVER:
            return False
        return UnitTypes.range_vs_target(attacker, target) > 0
    
    @staticmethod
    def can_be_attacked(unit: Unit, bot: BotAI, enemy_units: Units) -> bool:
        if unit.type_id in (UnitTypeId.DISRUPTORPHASED,):
            return False
        if not (unit.is_cloaked or unit.is_burrowed):
            return True
        is_mine = unit.owner_id == bot.player_id
        if is_mine and unit.energy <= 8:
            # cloak about to end so start retreating
            return True
        detectors: Units
        if is_mine:
            detectors = enemy_units.filter(lambda u: u.is_detector)
        else:
            detectors = bot.all_own_units.filter(lambda u: u.is_detector)
        for detector in detectors:
            bonus_detection_distance = 0
            if is_mine:
                bonus_detection_distance = 0.5 if detector.is_structure else 1
            if UnitTypes.distance_squared(detector, unit) <= (detector.sight_range + unit.radius + bonus_detection_distance) ** 2:
                return True
        for effect in bot.state.effects:
            if effect.id == EffectId.SCANNERSWEEP:
                for position in effect.positions:
                    if UnitTypes.distance_squared(position, unit) <= (13 + unit.radius) ** 2:
                        return True
        return False

    @staticmethod
    def count_units_by_type(units: Units, use_common_type: bool = True) -> Dict[UnitTypeId, int]:
        counts: Dict[UnitTypeId, int] = {}

        for unit in units:
            type_id = unit.unit_alias if use_common_type and unit.unit_alias else unit.type_id
            if type_id in UnitTypes.WORKER_TYPES:
                continue
            if type_id in (UnitTypeId.BUNKER, UnitTypeId.MEDIVAC):
                for passenger in unit.passengers:
                    if passenger.type_id in UnitTypes.WORKER_TYPES:
                        continue
                    counts[passenger.type_id] = counts.get(passenger.type_id, 0) + 1
            counts[type_id] = counts.get(type_id, 0) + 1

        return counts

    @staticmethod
    def group_units_by_type(units: Units, use_common_type: bool = True) -> Dict[UnitTypeId, List[Unit]]:
        counts: Dict[UnitTypeId, List[Unit]] = {}

        for unit in units:
            type_id = unit.unit_alias if use_common_type and unit.unit_alias else unit.type_id
            if type_id in UnitTypes.WORKER_TYPES:
                continue
            if type_id in (UnitTypeId.BUNKER, UnitTypeId.MEDIVAC):
                for passenger in unit.passengers:
                    if passenger.type_id in UnitTypes.WORKER_TYPES:
                        continue
                    counts.setdefault(passenger.type_id, []).append(passenger)
            counts.setdefault(type_id, []).append(unit)

        return counts

    @staticmethod
    def count_units_by_property(units: Units) -> Dict[str, int]:
        counts: Dict[str, int] = {
            'flying': 0,
            'ground': 0,
            'armored': 0,
            'biological': 0,
            'hidden': 0,
            'light': 0,
            'mechanical': 0,
            'psionic': 0,
            'attacks ground': 0,
            'attacks air': 0,
        }

        unit: Unit
        for unit in units:
            if unit.is_hallucination:
                continue
            if unit.is_flying:
                counts['flying'] += 1
            else:
                counts['ground'] += 1
            if unit.is_armored:
                counts['armored'] += 1
            if unit.is_biological:
                counts['biological'] += 1
            if unit.is_burrowed or unit.is_cloaked or not unit.is_visible:
                counts['hidden'] += 1
            if unit.is_light:
                counts['light'] += 1
            if unit.is_mechanical:
                counts['mechanical'] += 1
            if unit.is_psionic:
                counts['psionic'] += 1
            if UnitTypes.can_attack_ground(unit):
                counts['attacks ground'] += 1
            if UnitTypes.can_attack_air(unit):
                counts['attacks air'] += 1

        return counts
