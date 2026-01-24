from typing import Dict
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.enemy import Enemy
from bottato.enums import BuildType
from bottato.map.map import Map
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.custom_effect import CustomEffect
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.squad.enemy_intel import EnemyIntel
from bottato.unit_types import UnitTypes


class StructureMicro(BaseUnitMicro, GeometryMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, intel: EnemyIntel) -> None:
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.map: Map = map
        self.intel: EnemyIntel = intel
        self.command_center_destinations: Dict[int, Point2 | None] = {}
        self.last_scan_time: float = 0

    @timed_async
    async def execute(self, detected_enemy_builds: Dict[BuildType, float]):
        # logger.debug("adjust_supply_depots_for_enemies step")
        self.adjust_supply_depots_for_enemies(detected_enemy_builds)
        self.target_autoturrets()
        await self.move_command_centers()
        self.move_ramp_barracks()
        self.scan()

    @timed
    def adjust_supply_depots_for_enemies(self, detected_enemy_builds: Dict[BuildType, float]):
        # Raise depots when enemies are nearby
        distance_threshold = 8
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.is_flying:
                    continue
                if self.distance(enemy_unit, depot) < distance_threshold - 2:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    # fake effect to tell units to get off the depot
                    BaseUnitMicro.custom_effects_to_avoid.append(CustomEffect(depot.position, depot.radius, self.bot.time, 1))
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
            self._attack_something(turret, 0)

    @timed_async
    async def move_command_centers(self):
        for cc in self.bot.structures((UnitTypeId.COMMANDCENTER, UnitTypeId.COMMANDCENTERFLYING, UnitTypeId.ORBITALCOMMAND, UnitTypeId.ORBITALCOMMANDFLYING)).ready:
            if cc.is_flying:
                if cc.tag not in self.command_center_destinations:
                    self.command_center_destinations[cc.tag] = await self.bot.get_next_expansion()
                destination = self.command_center_destinations[cc.tag]
                if destination is None:
                    continue
                ccs_at_destination = self.bot.structures(UnitTypeId.COMMANDCENTER).closer_than(5, destination)
                if ccs_at_destination and cc.tag not in ccs_at_destination.tags:
                    # spot was taken, find a new one
                    self.command_center_destinations[cc.tag] = await self.bot.get_next_expansion()

                threats = self.bot.enemy_units.filter(lambda enemy: enemy.type_id not in UnitTypes.NON_THREATS)
                
                if cc.health_percentage < 0.3:
                    bunker = self.bot.structures(UnitTypeId.BUNKER)
                    if bunker:
                        if threats:
                            cc.move(bunker.first.position.towards(threats.center, -2))
                        else:
                            cc.move(bunker.first.position)
                    else:
                        cc.move(self.bot.main_base_ramp.top_center.towards(self.bot.start_location, 5))
                elif threats:
                    nearby_enemies = threats.closer_than(15, cc)
                    if nearby_enemies:
                        threats = nearby_enemies.filter(lambda enemy: UnitTypes.can_attack_air(enemy))
                        if cc.health_percentage < 0.9:
                            bunker = self.bot.structures(UnitTypeId.BUNKER)
                            if bunker:
                                if threats:
                                    cc.move(bunker.first.position.towards(threats.center, -2))
                                else:
                                    cc.move(bunker.first.position)
                            else:
                                cc.move(self.bot.main_base_ramp.top_center.towards(self.bot.start_location, 5))
                        elif threats:
                            cc.move(self.bot.main_base_ramp.top_center)
                        else:
                            cc.move(destination)
                        continue
                if cc.position == destination:
                    BaseUnitMicro.add_custom_effect(cc.position, cc.radius, self.bot.time, 0.5)
                    cc(AbilityId.LAND, destination)
                else:
                    cc.move(destination)
            else:
                for expansion_location in self.bot.expansion_locations_list:
                    if cc.position.distance_to(expansion_location) < 5:
                        break
                else:
                    if cc.type_id == UnitTypeId.ORBITALCOMMAND or self.bot.time > 240:
                        # upgrade to orbital first so it can generate energy while flying, unless the cc is late
                        cc(AbilityId.LIFT)
                        return
                if cc.health_percentage < 0.8 and self.bot.enemy_units:
                    nearby_enemies = self.enemy.threats_to_friendly_unit(cc, attack_range_buffer=2)
                    if nearby_enemies:
                        threats = nearby_enemies.filter(lambda enemy: UnitTypes.can_attack_ground(enemy))
                        if threats:
                            self.command_center_destinations[cc.tag] = cc.position
                            cc(AbilityId.CANCEL_LAST)
                            cc(AbilityId.LIFT)

    @timed
    def move_ramp_barracks(self):
        if self.bot.structures(UnitTypeId.BARRACKSREACTOR):
            # reactor already started, don't move barracks
            return
        if self.intel.enemy_race_confirmed != Race.Zerg \
                or BuildType.RUSH not in self.intel.enemy_builds_detected:
            return
        desired_position = self.bot.main_base_ramp.barracks_in_middle
        if desired_position is None:
            return
        barracks = self.bot.structures([UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING]).ready
        if barracks.amount != 1:
            return
        ramp_barracks = barracks.first
        is_in_position = ramp_barracks.position == desired_position
        if ramp_barracks.is_flying:
            if is_in_position:
                BaseUnitMicro.add_custom_effect(ramp_barracks.position, ramp_barracks.radius, self.bot.time, 0.5)
                ramp_barracks(AbilityId.LAND, desired_position)
            else:
                ramp_barracks.move(desired_position)
        elif not is_in_position:
            if ramp_barracks.orders:
                if ramp_barracks.orders[0].progress < 0.2:
                    ramp_barracks(AbilityId.CANCEL_LAST)
                    ramp_barracks(AbilityId.LIFT, queue=True)
            else:
                ramp_barracks(AbilityId.LIFT)


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
            most_grouped_enemy, grouped_enemies = self.get_most_grouped_unit(enemies_to_scan, self.bot, 13)
            orbital_with_energy(AbilityId.SCANNERSWEEP_SCAN, grouped_enemies.center)
            self.last_scan_time = self.bot.time