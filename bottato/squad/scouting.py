from typing import Dict

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.data import Race

from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.military import Military
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.squad import Squad
from bottato.squad.initial_scout import InitialScout
from bottato.squad.scout import Scout
from bottato.enemy import Enemy
from bottato.mixins import DebugMixin, timed_async
from bottato.economy.workers import Workers
from bottato.enums import BuildType, ScoutType
from bottato.unit_reference_helper import UnitReferenceHelper

class Scouting(Squad, DebugMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, workers: Workers,
                 military: Military, intel: EnemyIntel):
        super().__init__(bot=bot, color=self.random_color(), name="scouting")
        self.enemy = enemy
        self.map = map
        self.workers = workers
        self.military = military
        self.intel = intel
        self.enemy_builds_detected: Dict[BuildType, float] = {}
        self.initial_scan_done: bool = False

        self.friendly_territory = Scout("friendly territory", self.bot, enemy)
        self.enemy_territory = Scout("enemy territory", self.bot, enemy)
        self.initial_scout = InitialScout(self.bot, self.map, self.enemy, self.intel)
        self.newest_enemy_base = self.bot.enemy_start_locations[0]
        self.proxy_buildings: Units = Units([], self.bot)

        # positions to scout
        # used to identify newest bases to attack

        # assign all expansions locations to either friendly or enemy territory
        nearest_locations_temp = sorted(self.intel.scouting_locations,
                                        key=lambda location: (location.scouting_position - self.bot.start_location).length)
        enemy_nearest_locations_temp = sorted(self.intel.scouting_locations,
                                              key=lambda location: (location.scouting_position - self.bot.enemy_start_locations[0]).length)
        self.enemy_main = enemy_nearest_locations_temp[0]
        for i in range(len(nearest_locations_temp)):
            if not self.enemy_territory.contains_location(nearest_locations_temp[i]):
                self.friendly_territory.add_location(nearest_locations_temp[i])
            if not self.friendly_territory.contains_location(enemy_nearest_locations_temp[i]):
                self.enemy_territory.add_location(enemy_nearest_locations_temp[i])
    
    def get_intel(self) -> EnemyIntel:
        return self.intel

    def init_scouting_routes(self):
        self.friendly_territory.traveling_salesman_sort(self.map)
        self.enemy_territory.traveling_salesman_sort()

    def update_visibility(self):
        self.intel.catalog_visible_units()
        scout_units = [u for u in (self.friendly_territory.unit, self.enemy_territory.unit) if u]
        self.intel.update_location_visibility(scout_units)

    async def detect_enemy_build(self):
        if self.intel.enemy_race_confirmed is None:
            return
        if self.proxy_detected():
            await LogHelper.add_chat("proxy suspected")
            self.add_detected_build(BuildType.PROXY)
        if self.bot.time < 60:
            rushing_enemy_workers = self.bot.enemy_units.filter(
                lambda u: u.distance_to(self.bot.start_location) - 15 < u.distance_to(self.bot.enemy_start_locations[0]))
            if rushing_enemy_workers.amount >= 3:
                await LogHelper.add_chat("worker rush detected")
                self.add_detected_build(BuildType.WORKER_RUSH)
        if self.intel.enemy_race_confirmed == Race.Zerg:
            early_pool = self.intel.first_building_time.get(UnitTypeId.SPAWNINGPOOL, 9999) < 40
            no_gas = self.initial_scout.completed and self.intel.number_seen(UnitTypeId.EXTRACTOR) == 0
            no_expansion = self.initial_scout.completed and self.intel.number_seen(UnitTypeId.HATCHERY) == 1
            zergling_rush = self.enemy.get_total_count_of_type_seen(UnitTypeId.ZERGLING) >= 8 and self.bot.time < 180
            if early_pool:
                await LogHelper.add_chat("early pool detected")
            if no_gas:
                await LogHelper.add_chat("no gas detected")
            if no_expansion:
                await LogHelper.add_chat("no expansion detected")
            if zergling_rush:
                await LogHelper.add_chat("zergling rush detected")
                self.add_detected_build(BuildType.ZERGLING_RUSH)
            if early_pool or no_gas or no_expansion or zergling_rush:
                self.add_detected_build(BuildType.RUSH)
        elif self.intel.enemy_race_confirmed == Race.Terran:
            # no_expansion = self.intel.number_seen(UnitTypeId.COMMANDCENTER) == 1 and self.initial_scout.completed
            battlecruiser = self.bot.time < 360 and \
                (self.intel.number_seen(UnitTypeId.FUSIONCORE) > 0 or
                 self.intel.number_seen(UnitTypeId.BATTLECRUISER) > 0)
            if battlecruiser:
                await LogHelper.add_chat("battlecruiser rush detected")
                self.add_detected_build(BuildType.BATTLECRUISER_RUSH)
            multiple_barracks = not self.initial_scout.completed and self.intel.number_seen(UnitTypeId.BARRACKS) > 1
            if multiple_barracks:
                await LogHelper.add_chat("multiple early barracks detected")
            # if no_expansion:
            #     await LogHelper.add_chat("no expansion detected")
            if multiple_barracks:
                self.add_detected_build(BuildType.RUSH)
        else:
            # Protoss
            lots_of_gateways = not self.initial_scout.completed and self.intel.number_seen(UnitTypeId.GATEWAY) > 2
            no_expansion = self.initial_scout.completed and self.intel.number_seen(UnitTypeId.NEXUS) == 1
            early_stargate = self.intel.number_seen(UnitTypeId.STARGATE) > 0
            fleet_beacon = self.intel.number_seen(UnitTypeId.FLEETBEACON) > 0
            if lots_of_gateways:
                await LogHelper.add_chat("lots of gateways detected")
            if no_expansion:
                await LogHelper.add_chat("no expansion detected")
            if early_stargate:
                await LogHelper.add_chat("stargate detected")
                self.add_detected_build(BuildType.STARGATE)
            if fleet_beacon:
                await LogHelper.add_chat("fleet beacon detected")
                self.add_detected_build(BuildType.FLEET_BEACON)
            if lots_of_gateways or no_expansion:
                self.add_detected_build(BuildType.RUSH)
            
            if self.bot.time < 180 and len(self.bot.enemy_units) > 0 and len(self.bot.enemy_units.closer_than(30, self.bot.start_location)) > 5:
                await LogHelper.add_chat("early army detected near base")
                self.add_detected_build(BuildType.RUSH)
    
    def add_detected_build(self, build_type: BuildType):
        if build_type not in self.enemy_builds_detected:
            self.enemy_builds_detected[build_type] = self.bot.time
    
    def proxy_detected(self) -> bool:
        if self.intel.enemy_race_confirmed is None or self.bot.time > 120:
            return False
        if self.proxy_buildings:
            return True
        if self.intel.enemy_race_confirmed == Race.Zerg:
            # are zerg proxy a thing?
            return False
        if self.intel.enemy_race_confirmed == Race.Terran:
            if self.bot.enemy_units(UnitTypeId.BATTLECRUISER) and self.intel.number_seen(UnitTypeId.STARPORT) == 0:
                return True
            return self.initial_scout.main_scouted and self.intel.number_seen(UnitTypeId.BARRACKS) == 0
        return self.bot.time > 100 and self.intel.number_seen(UnitTypeId.GATEWAY) == 0

    @timed_async
    async def scout(self, new_damage_taken: dict[int, float]):
        # Update scout unit references
        friendly_scout_type = ScoutType.ANY if BuildType.PROXY in self.enemy_builds_detected or self.bot.time > 120 else ScoutType.NONE
        self.friendly_territory.update_scout(self.military, self.workers, friendly_scout_type)
        self.enemy_territory.update_scout(self.military, self.workers, ScoutType.VIKING)
        if self.enemy_builds_detected:
            self.initial_scout.completed = True
        self.initial_scout.update_scout(self.workers)

        self.update_visibility()

        await self.initial_scout.move_scout()

        # Move scouts
        await self.friendly_territory.move_scout(new_damage_taken)
        await self.enemy_territory.move_scout(new_damage_taken)

        i = len(self.proxy_buildings) - 1
        while i >= 0:
            if self.bot.is_visible(self.proxy_buildings[i].position):
                try:
                    self.proxy_buildings[i] = UnitReferenceHelper.get_updated_unit_reference(self.proxy_buildings[i])
                except Exception as e:
                    LogHelper.add_log(f"proxy building no longer detected: {self.proxy_buildings[i]}")
                    self.proxy_buildings.remove(self.proxy_buildings[i])
            i -= 1

        if self.bot.time < 420:
            scouted_structures = self.bot.enemy_structures.filter(lambda s: s.is_visible)
            for structure in scouted_structures:
                if structure.position.manhattan_distance(self.bot.start_location) > structure.position.manhattan_distance(self.enemy_main.expansion_position):
                    continue
                for proxy_structure in self.proxy_buildings:
                    if structure.type_id == proxy_structure.type_id and structure.position.manhattan_distance(proxy_structure.position) < 1:
                        break
                else:
                    if structure.type_id not in (UnitTypeId.PYLON, UnitTypeId.PHOTONCANNON, UnitTypeId.PLANETARYFORTRESS, UnitTypeId.BUNKER):
                        self.proxy_buildings.append(structure)
                        LogHelper.add_log(f"proxy building detected: {structure}")

    @property
    async def detected_enemy_builds(self) -> Dict[BuildType, float]:
        if not self.initial_scan_done and 165 < self.bot.time < 210:
            reaper = self.bot.units(UnitTypeId.REAPER)
            if not reaper or reaper.first.distance_to(self.enemy_main.scouting_position) > 25:
                if self.enemy_main.needs_fresh_scouting(self.bot.time, skip_occupied=False):
                    for orbital in self.bot.townhalls(UnitTypeId.ORBITALCOMMAND).ready:
                        if orbital.energy >= 50:
                            orbital(AbilityId.SCANNERSWEEP_SCAN, self.bot.enemy_start_locations[0])
                            self.initial_scan_done = True
                            break

        await self.detect_enemy_build()
        return self.enemy_builds_detected