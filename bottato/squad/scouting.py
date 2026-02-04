from typing import Dict

from cython_extensions.geometry import cy_distance_to
from sc2.bot_ai import BotAI
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId

from bottato.economy.workers import Workers
from bottato.enemy import Enemy
from bottato.enums import BuildType, ExpansionSelection, ScoutType
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.military import Military
from bottato.mixins import DebugMixin, timed_async
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.initial_scout import InitialScout
from bottato.squad.scout import Scout
from bottato.squad.squad import Squad
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
        self.initial_scan_done: bool = False

        self.friendly_territory = Scout("friendly territory", self.bot, enemy)
        self.enemy_territory = Scout("enemy territory", self.bot, enemy)
        self.initial_scout = InitialScout(self.bot, self.map, self.enemy, self.intel)
        self.newest_enemy_base = self.bot.enemy_start_locations[0]

    def init_scouting_routes(self):
        # assign all expansions locations to either friendly or enemy territory
        nearest_locations_temp = self.map.expansion_orders[ExpansionSelection.CLOSEST]
        enemy_nearest_locations_temp = self.map.enemy_expansion_orders[ExpansionSelection.CLOSEST]
        
        self.enemy_main = enemy_nearest_locations_temp[0]
        for i in range(len(nearest_locations_temp)):
            if not self.enemy_territory.contains_location(nearest_locations_temp[i]):
                self.friendly_territory.add_location(nearest_locations_temp[i])
            if not self.friendly_territory.contains_location(enemy_nearest_locations_temp[i]):
                self.enemy_territory.add_location(enemy_nearest_locations_temp[i])
                
        self.friendly_territory.traveling_salesman_sort(self.map)
        self.enemy_territory.traveling_salesman_sort()

    def update_visibility(self):
        scout_units = [u for u in (self.friendly_territory.unit, self.enemy_territory.unit) if u]
        self.intel.update_location_visibility(scout_units)

    @timed_async
    async def scout(self, new_damage_taken: dict[int, float]):
        # Update scout unit references
        self.initial_scout.update_scout(self.workers)
        
        friendly_scout_type = ScoutType.ANY if BuildType.PROXY in self.intel.enemy_builds_detected or self.bot.time > 120 else ScoutType.NONE
        self.friendly_territory.update_scout(self.military, self.workers, friendly_scout_type)
        self.enemy_territory.update_scout(self.military, self.workers, ScoutType.VIKING)

        self.update_visibility()

        await self.initial_scout.move_scout()

        # Move scouts
        await self.friendly_territory.move_scout(new_damage_taken)
        await self.enemy_territory.move_scout(new_damage_taken)

        i = len(self.intel.proxy_buildings) - 1
        while i >= 0:
            if self.bot.is_visible(self.intel.proxy_buildings[i].position):
                try:
                    self.intel.proxy_buildings[i] = UnitReferenceHelper.get_updated_unit_reference(self.intel.proxy_buildings[i])
                except Exception as e:
                    LogHelper.add_log(f"proxy building no longer detected: {self.intel.proxy_buildings[i]}")
                    self.intel.proxy_buildings.remove(self.intel.proxy_buildings[i])
            i -= 1

        if self.bot.time < 420:
            scouted_structures = self.bot.enemy_structures.filter(lambda s: s.is_visible)
            for structure in scouted_structures:
                if structure.position.manhattan_distance(self.bot.start_location) > structure.position.manhattan_distance(self.enemy_main.expansion_position):
                    continue
                for proxy_structure in self.intel.proxy_buildings:
                    if structure.type_id == proxy_structure.type_id and structure.position.manhattan_distance(proxy_structure.position) < 1:
                        break
                else:
                    if structure.type_id not in (UnitTypeId.PYLON, UnitTypeId.PHOTONCANNON, UnitTypeId.PLANETARYFORTRESS, UnitTypeId.BUNKER):
                        self.intel.proxy_buildings.append(structure)
                        LogHelper.add_log(f"proxy building detected: {structure}")

        if not self.initial_scan_done and 165 < self.bot.time < 210:
            reaper = self.bot.units(UnitTypeId.REAPER)
            if not reaper or cy_distance_to(reaper.first.position, self.enemy_main.scouting_position) > 25:
                if self.enemy_main.needs_fresh_scouting(self.bot.time, skip_occupied=False):
                    for orbital in self.bot.townhalls(UnitTypeId.ORBITALCOMMAND).ready:
                        if orbital.energy >= 50:
                            orbital(AbilityId.SCANNERSWEEP_SCAN, self.bot.enemy_start_locations[0])
                            self.initial_scan_done = True
                            break
