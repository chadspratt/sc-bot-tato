from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.constants import UnitTypeId

from bottato.map.map import Map
from bottato.military import Military
from bottato.squad.base_squad import BaseSquad
from bottato.enemy import Enemy
from bottato.mixins import DebugMixin, UnitReferenceMixin
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.economy.workers import Workers


class ScoutingLocation:
    def __init__(self, position: Point2):
        self.position: Point2 = position
        self.last_seen: int = None

    def __repr__(self) -> str:
        return f"ScoutingLocation({self.position}, {self.last_seen})"


class Scout(UnitReferenceMixin):
    def __init__(self, name, bot: BotAI, enemy: Enemy):
        self.name: str = name
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.unit: Unit = None
        self.scouting_locations: List[ScoutingLocation] = list()
        self.scouting_locations_index: int = 0

    def __repr__(self):
        return f"{self.name} scouts: {self.unit}, locations: {self.scouting_locations}"

    def add_location(self, scouting_location: ScoutingLocation):
        self.scouting_locations.append(scouting_location)

    def contains_location(self, scouting_location: ScoutingLocation):
        return scouting_location in self.scouting_locations

    @property
    def scouts_needed(self) -> int:
        return 0 if self.unit else 1
    
    def needs(self, unit: Unit) -> bool:
        return unit.type_id in (UnitTypeId.SCV, UnitTypeId.MARINE, UnitTypeId.REAPER)

    def update_scout(self):
        """Update unit reference for this scout"""
        if self.unit:
            try:
                self.unit = self.get_updated_unit_reference(self.unit)
                logger.debug(f"{self.name} scout {self.unit}")
            except self.UnitNotFound:
                self.unit = None
                pass

    async def move_scout(self, new_damage_taken: dict[int, float]):
        assignment: ScoutingLocation = self.scouting_locations[self.scouting_locations_index]
        logger.debug(f"scout {self.unit} previous assignment: {assignment}")

        micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.unit, self.bot, self.enemy)

        # move to next location if taking damage
        next_index = self.scouting_locations_index
        if self.unit.tag in new_damage_taken:
            next_index = (next_index + 1) % len(self.scouting_locations)
            assignment: ScoutingLocation = self.scouting_locations[next_index]
            logger.debug(f"scout {self.unit} took damage, changing assignment")

        while assignment.last_seen and self.bot.time - assignment.last_seen < 10:
            next_index = (next_index + 1) % len(self.scouting_locations)
            if next_index == self.scouting_locations_index:
                # full cycle, none need scouting
                break
            assignment: ScoutingLocation = self.scouting_locations[next_index]
        self.scouting_locations_index = next_index
        logger.debug(f"scout {self.unit} new assignment: {assignment}")

        await micro.scout(self.unit, assignment.position, self.enemy)


class Scouting(BaseSquad, DebugMixin):
    worker_scout_time = 30
    initial_scout_complete_time = 150

    rush_detected = False
    enemy_workers_away_from_base = 0
    pool_start_time = None

    def __init__(self, bot: BotAI, enemy: Enemy, map: Map):
        super().__init__(bot=bot, color=self.random_color(), name="scouting")
        self.bot = bot
        self.enemy = enemy
        self.map = map
        self.scouting_locations: List[ScoutingLocation] = list()
        self.units: Units = Units([], bot)
        self.worker_scout: Unit = None
        self.initial_scout_completed: bool = False

        self.friendly_territory = Scout("friendly territory", self.bot, enemy)
        self.enemy_territory = Scout("enemy territory", self.bot, enemy)

        # assign all expansions locations to either friendly or enemy territory
        for expansion_location in self.bot.expansion_locations_list:
            self.scouting_locations.append(ScoutingLocation(expansion_location))
        nearest_locations_temp = sorted(self.scouting_locations, key=lambda location: (location.position - self.bot.start_location).length)
        enemy_nearest_locations_temp = sorted(self.scouting_locations, key=lambda location: (location.position - self.bot.enemy_start_locations[0]).length)
        for i in range(len(nearest_locations_temp)):
            if not self.enemy_territory.contains_location(nearest_locations_temp[i]):
                self.friendly_territory.add_location(nearest_locations_temp[i])
            if not self.friendly_territory.contains_location(enemy_nearest_locations_temp[i]):
                self.enemy_territory.add_location(enemy_nearest_locations_temp[i])

        logger.debug(f"friendly_territory {self.friendly_territory}")
        logger.debug(f"enemy_territory {self.enemy_territory}")

    def update_scouts(self, workers: Workers, military: Military):
        # Update scout unit references
        self.friendly_territory.update_scout()
        self.enemy_territory.update_scout()
        try:
            self.worker_scout = self.get_updated_unit_reference(self.worker_scout)
        except self.UnitNotFound:
            self.worker_scout = None
        if self.initial_scout_completed or self.bot.time > self.initial_scout_complete_time + 40:
            self.initial_scout_completed = True
            if self.worker_scout is not None:
                workers.set_as_idle(self.worker_scout)
                self.worker_scout = None
        elif self.bot.time > self.worker_scout_time and self.worker_scout is None:
            self.worker_scout = workers.get_scout(self.map.enemy_natural_position)

        # start territory scouting if enemy main is empty
        if self.bot.is_visible(self.bot.enemy_start_locations[0]) and not self.bot.enemy_structures.closer_than(10, self.bot.enemy_start_locations[0]):
            if self.friendly_territory.scouts_needed:
                for unit in military.main_army.units:
                    if self.friendly_territory.needs(unit):
                        military.transfer(unit, military.main_army, self)
                        self.friendly_territory.unit = unit
                        break
            if self.enemy_territory.scouts_needed:
                for unit in military.main_army.units:
                    if self.enemy_territory.needs(unit):
                        military.transfer(unit, military.main_army, self)
                        self.enemy_territory.unit = unit
                        break

    @property
    def scouts_needed(self):
        return self.friendly_territory.scouts_needed + self.enemy_territory.scouts_needed

    def update_visibility(self):
        for location in self.scouting_locations:
            if self.bot.is_visible(location.position):
                location.last_seen = self.bot.time

    async def move_scouts(self, new_damage_taken: dict[int, float]):
        self.units = self.get_updated_unit_references(self.units)
        
        # Handle worker scout movement
        if self.worker_scout:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.worker_scout, self.bot, self.enemy)
            await micro.scout(self.worker_scout, self.map.enemy_natural_position, self.enemy)
            if self.bot.is_visible(self.map.enemy_natural_position) and self.bot.time > self.initial_scout_complete_time:
                self.initial_scout_completed = True

                # Set one_base_detected if there is an enemy town hall on or near the expansion location
                enemy_townhalls = self.bot.enemy_structures.of_type([
                    UnitTypeId.COMMANDCENTER,
                    UnitTypeId.ORBITALCOMMAND,
                    UnitTypeId.PLANETARYFORTRESS,
                    UnitTypeId.HATCHERY,
                    UnitTypeId.LAIR,
                    UnitTypeId.HIVE,
                    UnitTypeId.NEXUS
                ])
                for th in enemy_townhalls:
                    if th.position.distance_to(self.map.enemy_natural_position) < 5:
                        break
                else:
                    self.rush_detected = True

        # Move scouts
        if self.friendly_territory.unit:
            await self.friendly_territory.move_scout(new_damage_taken)
        if self.enemy_territory.unit:
            await self.enemy_territory.move_scout(new_damage_taken)
