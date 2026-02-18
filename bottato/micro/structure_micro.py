from loguru import logger
from typing import Dict

from cython_extensions.geometry import cy_distance_to, cy_towards
from cython_extensions.units_utils import cy_center, cy_closer_than
from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.enemy import Enemy
from bottato.enums import BuildType, CustomEffectType, ExpansionSelection, Tactic
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.custom_effect import CustomEffect
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.squad.enemy_intel import EnemyIntel
from bottato.tactics import Tactics
from bottato.unit_reference_helper import UnitReferenceHelper
from bottato.unit_types import UnitTypes


class StructureMicro(BaseUnitMicro, GeometryMixin):
    def __init__(self, bot: BotAI, tactics: Tactics) -> None:
        self.bot: BotAI = bot
        self.tactics: Tactics = tactics
        self.enemy: Enemy = tactics.enemy
        self.map: Map = tactics.map
        self.intel: EnemyIntel = tactics.intel
        self.building_destinations: Dict[int, Point2 | None] = {}
        self.building_in_position_times: Dict[int, float | None] = {}
        self.last_scan_time: float = 0
        self.last_lift_for_unstuck: Dict[int, float] = {}
        self.destinations: Dict[int, Point2] = {}

    @timed_async
    async def execute(self, army_ratio: float, stuck_units: Units):
        # logger.debug("adjust_supply_depots_for_enemies step")
        self.adjust_supply_depots_for_enemies()
        self.target_autoturrets()
        await self.move_command_centers()
        await self.move_ramp_barracks(army_ratio)
        await self.move_proxy_barracks()
        self.scan()
        await self.untrap_stuck_units(stuck_units)

    @timed
    def adjust_supply_depots_for_enemies(self):
        # Raise depots when enemies are nearby
        distance_threshold = 8
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.is_flying:
                    continue
                if self.distance(enemy_unit, depot) < distance_threshold - 2:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    # fake effect to tell units to get off the depot
                    BaseUnitMicro.custom_effects_to_avoid.append(CustomEffect(CustomEffectType.BUILDING_FOOTPRINT, depot.position, depot.radius, self.bot.time, 1))
                    break
        # Lower depots when no enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.is_flying:
                    continue
                if self.distance(enemy_unit, depot) < distance_threshold:
                    break
            else:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    @timed
    def target_autoturrets(self):
        turret: Unit
        for turret in self.bot.structures(UnitTypeId.AUTOTURRET):
            logger.debug(f"turret {turret} attacking")
            self._attack_something(turret, 0, move_position=turret.position)

    # @timed
    # should more structures fly away or is it better for them to stay and die to delay the enemy
    # def retreat_from_threats(self):
    #     flyable_structures = self.bot.structures.of_type(UnitTypes.FLYABLE_STRUCTURE_TYPES).ready
    #     for structure in flyable_structures:
    #         threats = self.bot.enemy_units.filter(lambda enemy: enemy.type_id not in UnitTypes.NON_THREATS)
    #         threats = self.enemy.threats_to_friendly_unit(structure, attack_range_buffer=2)
    #         if threats:
    #             nearby_enemies = Units(cy_closer_than(threats, 15, structure.position), bot_object=self.bot)
    #             if nearby_enemies:
    #                 threats = nearby_enemies.filter(lambda enemy: UnitTypes.can_attack_ground(enemy))
    #                 if threats:
    #                     structure.move(Point2(cy_towards(self.bot.main_base_ramp.top_center, self.bot.start_location, 5)))
    #                     break

    @timed_async
    async def move_command_centers(self):
        for cc in self.bot.structures((UnitTypeId.COMMANDCENTER, UnitTypeId.COMMANDCENTERFLYING, UnitTypeId.ORBITALCOMMAND, UnitTypeId.ORBITALCOMMANDFLYING)).ready:
            if cc.is_flying:
                destination = self.building_destinations.get(cc.tag, None)
                if destination:
                    ccs_at_destination = Units(cy_closer_than(self.bot.townhalls, 5, destination), bot_object=self.bot)
                    if ccs_at_destination and cc.tag not in ccs_at_destination.tags:
                        # spot was taken, find a new one
                        destination = None
                if destination is None:
                    destination = self.map.get_next_expansion()
                    self.building_destinations[cc.tag] = destination
                    if destination is None:
                        cc(AbilityId.LAND, cc.position)
                        continue

                threats = self.bot.enemy_units.filter(lambda enemy: enemy.type_id not in UnitTypes.NON_THREATS)
                
                if cc.health_percentage < 0.3:
                    bunker = self.bot.structures(UnitTypeId.BUNKER)
                    if bunker:
                        if threats:
                            cc.move(Point2(cy_towards(bunker.first.position, Point2(cy_center(threats)), -2)))
                        else:
                            cc.move(bunker.first.position)
                    else:
                        cc.move(Point2(cy_towards(self.bot.main_base_ramp.top_center, self.bot.start_location, 5)))
                elif threats:
                    nearby_enemies = Units(cy_closer_than(threats, 15, cc.position), bot_object=self.bot)
                    if nearby_enemies:
                        threats = nearby_enemies.filter(lambda enemy: UnitTypes.can_attack_air(enemy))
                        if cc.health_percentage < 0.9:
                            bunker = self.bot.structures(UnitTypeId.BUNKER)
                            if bunker:
                                if threats:
                                    cc.move(Point2(cy_towards(bunker.first.position, Point2(cy_center(threats)), -2)))
                                else:
                                    cc.move(bunker.first.position)
                            else:
                                cc.move(Point2(cy_towards(self.bot.main_base_ramp.top_center, self.bot.start_location, 5)))
                        elif threats:
                            cc.move(self.bot.main_base_ramp.top_center)
                        else:
                            cc.move(destination)
                        continue
                if cc.position == destination:
                    BaseUnitMicro.add_custom_effect(CustomEffectType.BUILDING_FOOTPRINT, cc.position, cc.radius + 0.5, self.bot.time, 0.5)
                    cc(AbilityId.LAND, destination)
                else:
                    cc.move(destination)
            else:
                for expansion_location in self.bot.expansion_locations_list:
                    if cy_distance_to(cc.position, expansion_location) < 5:
                        break
                else:
                    cc(AbilityId.LIFT)
                    return
                if cc.health_percentage < 0.8 and self.bot.enemy_units:
                    nearby_enemies = self.enemy.threats_to_friendly_unit(cc, attack_range_buffer=2)
                    if nearby_enemies:
                        threats = nearby_enemies.filter(lambda enemy: UnitTypes.can_attack_ground(enemy))
                        if threats:
                            self.building_destinations[cc.tag] = cc.position
                            cc(AbilityId.CANCEL_LAST)
                            cc(AbilityId.CANCEL, queue=True)
                            cc(AbilityId.LIFT, queue=True)

    @timed_async
    async def move_ramp_barracks(self, army_ratio: float):
        if self.bot.structures(UnitTypeId.BARRACKSREACTOR):
            # reactor already started, don't move barracks
            return

        barracks = Units(cy_closer_than(self.bot.structures([UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING]).ready, 5, self.bot.main_base_ramp.top_center), bot_object=self.bot)
        if barracks.amount == 0:
            return
        ramp_barracks = barracks.first

        desired_position = self.building_destinations.get(ramp_barracks.tag)
        if desired_position is None:
            desired_position = self.bot.main_base_ramp.barracks_correct_placement
            if desired_position is None:
                return
            self.building_destinations[ramp_barracks.tag] = desired_position

        is_in_position = ramp_barracks.position == desired_position
        if not is_in_position:
            # Check if natural townhall is in position
            natural_townhalls = cy_closer_than(self.bot.townhalls, 1, self.map.natural_position)
            if not natural_townhalls:
                return
            if cy_closer_than(self.bot.enemy_units, 25, ramp_barracks.position):
                # don't move if enemies are nearby
                return
            
            await self.move_structure(ramp_barracks)

    async def move_structure(self, structure: Unit) -> bool:
        destination = self.building_destinations.get(structure.tag)
        if destination is None:
            destination = await self.get_unit_placement(structure)
            if destination is None:
                return False
            self.building_destinations[structure.tag] = destination
        distance = destination.manhattan_distance(structure.position)
        if distance > 1:
            if structure.is_flying:
                await self.move(structure, destination)
            else:
                structure(AbilityId.LIFT)
        else:
            if structure.is_flying:
                in_position_time = self.building_in_position_times.get(structure.tag)
                if in_position_time is None:
                    self.building_in_position_times[structure.tag] = self.bot.time
                elif self.bot.time - in_position_time > 2 and not await self.bot.can_place_single(UnitTypeId.BARRACKS, destination):
                    # unable to land, find new position
                    type_id = structure.unit_alias if structure.unit_alias else structure.type_id
                    new_destination = self.building_destinations[structure.tag] = await self.bot.find_placement(type_id, destination, placement_step=1, addon_place=True)
                    self.building_in_position_times[structure.tag] = None
                    if new_destination:
                        await self.move(structure, new_destination)
                else:
                    BaseUnitMicro.add_custom_effect(CustomEffectType.BUILDING_FOOTPRINT, structure.position, structure.radius, self.bot.time, 0.5)
                    structure(AbilityId.LAND, destination)
            else:
                # landed in position
                self.building_destinations[structure.tag] = None
                self.building_in_position_times[structure.tag] = None
                return True
        return False

    async def move_proxy_barracks(self):
        if BuildType.EARLY_EXPANSION in self.intel.enemy_builds_detected:
            proxy_is_active = self.tactics.is_active(Tactic.PROXY_BARRACKS)
            if self.tactics.proxy_barracks and not proxy_is_active:
                move_complete = await self.move_structure(self.tactics.proxy_barracks)
                if move_complete:
                    self.tactics.proxy_barracks = None

    async def get_unit_placement(self, unit: Unit, near: Point2 | None = None) -> Point2 | None:
        if near is None:
            near = self.map.natural_position.towards(self.bot.game_info.map_center, 8)
        if unit.type_id in (UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING):
            return await self.bot.find_placement(UnitTypeId.BARRACKS, near, placement_step=1, addon_place=True)
        elif unit.type_id in (UnitTypeId.FACTORY, UnitTypeId.FACTORYFLYING):
            return await self.bot.find_placement(UnitTypeId.FACTORY, near, placement_step=1, addon_place=True)
        elif unit.type_id in (UnitTypeId.STARPORT, UnitTypeId.STARPORTFLYING):
            return await self.bot.find_placement(UnitTypeId.STARPORT, near, placement_step=1, addon_place=True)
        return None

    @timed_async
    async def untrap_stuck_units(self, stuck_units: Units):
        """Lift up barracks/factories/starports if stuck units are touching them."""        
        liftable_structures = self.bot.structures([
            UnitTypeId.BARRACKS,
            UnitTypeId.FACTORY,
            UnitTypeId.STARPORT,
            UnitTypeId.BARRACKSFLYING,
            UnitTypeId.FACTORYFLYING,
            UnitTypeId.STARPORTFLYING
        ]).ready
        
        for structure in liftable_structures:
            if structure.tag in self.last_lift_for_unstuck:
                time_since_last_lift = self.bot.time - self.last_lift_for_unstuck[structure.tag]
                if time_since_last_lift < 2:
                    continue  # recently lifted, skip
                if structure.is_flying:
                    structure(AbilityId.LAND, self.destinations[structure.tag])
                else:
                    del self.last_lift_for_unstuck[structure.tag]
                    if structure.tag in self.destinations:
                        del self.destinations[structure.tag]
            # Check if any stuck unit is touching this structure
            if not structure.is_flying:
                # Don't lift if currently building something
                if structure.orders:
                    continue
                for stuck_unit in stuck_units:
                    # Unit is touching if distance is less than sum of radii
                    distance = cy_distance_to(structure.position, stuck_unit.position)
                    if distance < (structure.radius + stuck_unit.radius + 0.5):
                        LogHelper.write_log_to_db("debug", f"Lifting {structure} to untrap unit")
                        self.last_lift_for_unstuck[structure.tag] = self.bot.time
                        if structure.has_add_on:
                            self.destinations[structure.tag] = structure.position
                        else:
                            unit_type = structure.unit_alias if structure.unit_alias else structure.type_id
                            new_position = await self.bot.find_placement(unit_type, structure.position, placement_step=1, addon_place=True)
                            if new_position:
                                self.destinations[structure.tag] = new_position
                            else:
                                self.destinations[structure.tag] = structure.position
                        structure(AbilityId.LIFT)
                        break

    @timed
    def scan(self):
        if self.bot.time - self.last_scan_time < 9:
            return
        orbital_with_energy = None
        for orbital in self.bot.structures(UnitTypeId.ORBITALCOMMAND).ready:
            if orbital.energy >= 50:
                orbital_with_energy = orbital
                break
        else:
            return
        need_detection = self.enemy.enemies_needing_detection()

        ravens = self.bot.units(UnitTypeId.RAVEN)
        enemies_to_scan = Units([], self.bot)
        air_attackers = None
        ground_attackers = None
        for enemy in need_detection:
            attackers = None
            # don't scan if raven nearby
            if self.closest_distance_squared(enemy, ravens) < 400:
                continue
            # only scan enemies if attackers nearby to make use of scan
            if enemy.is_flying:
                if air_attackers is None:
                    air_attackers = self.bot.units.filter(lambda u: UnitTypes.can_attack_air(u))
                attackers = air_attackers
            else:
                if ground_attackers is None:
                    ground_attackers = self.bot.units.filter(lambda u: UnitTypes.can_attack_ground(u))
                attackers = ground_attackers
            if not attackers:
                continue
            attackers = self.enemy.threats_to(enemy, attackers)
            if attackers.amount > 1:
                enemies_to_scan.append(enemy)

        # find unit that has most hidden enemies nearby then scan center of the group
        if enemies_to_scan:
            _, grouped_enemies = self.get_most_grouped_unit(enemies_to_scan, self.bot, 13)
            orbital_with_energy(AbilityId.SCANNERSWEEP_SCAN, Point2(cy_center(grouped_enemies)))
            self.last_scan_time = self.bot.time