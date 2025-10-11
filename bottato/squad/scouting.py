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


class Scout(BaseSquad, UnitReferenceMixin):
    def __init__(self, name, bot: BotAI, enemy: Enemy):
        self.name: str = name
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.unit: Unit = None
        self.scouting_locations: List[ScoutingLocation] = list()
        self.scouting_locations_index: int = 0
        super().__init__(bot=bot, name="scout")

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

    def update_scout(self, military: Military):
        """Update unit reference for this scout"""
        if self.unit:
            try:
                self.unit = self.get_updated_unit_reference(self.unit)
                logger.debug(f"{self.name} scout {self.unit}")
            except self.UnitNotFound:
                self.unit = None
                pass
        elif self.bot.is_visible(self.bot.enemy_start_locations[0]) and not self.bot.enemy_structures.closer_than(10, self.bot.enemy_start_locations[0]):
            # start territory scouting if enemy main is empty
            if self.scouts_needed:
                for unit in military.main_army.units:
                    if self.needs(unit):
                        military.transfer(unit, military.main_army, self)
                        self.unit = unit
                        break
                else:
                    # no marines or reapers, use a worker
                    if self.bot.workers:
                        self.unit = self.bot.workers.random
                    else:
                        # unlikely, but fallback to any unit
                        for unit in military.main_army.units:
                            military.transfer(unit, military.main_army, self)
                            self.unit = unit
                            break

    async def move_scout(self, new_damage_taken: dict[int, float]):
        if not self.unit:
            return
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

class InitialScout(BaseSquad):
    bot: BotAI = None
    map: Map = None

    unit: Unit = None
    completed: bool = False
    rush_detected: bool = False
    enemy_natural_delayed: bool = False

    main_scouted: bool = False
    main_scoutable: bool = True
    natural_expansion_time: float = None
    enemy_workers_away_from_base: int = 0

    start_time = 30
    initial_scout_complete_time = 190

    # zerg specific
    pool_start_time: float = None

    def __init__(self, bot: BotAI, map: Map, enemy: Enemy):
        self.bot = bot
        self.map = map
        self.enemy = enemy

    def update_scout(self, workers: Workers):
        if self.bot.time < self.start_time:
            # too early to scout
            return
        if self.unit:
            try:
                self.unit = self.get_updated_unit_reference(self.unit)
            except self.UnitNotFound:
                self.unit = None
                return

            if self.completed:
                workers.set_as_idle(self.unit)
                self.unit = None
                return
        if not self.unit and not self.completed:
            self.unit = workers.get_scout(self.map.enemy_natural_position)
    
    async def move_scout(self):
        if not self.unit or self.completed:
            return
        if self.enemy_natural_is_built():
            self.completed = True
        elif self.bot.time > self.initial_scout_complete_time:
            self.enemy_natural_delayed = True
            self.completed = True
        else:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.unit, self.bot, self.enemy)
            await micro.scout(self.unit, self.map.enemy_natural_position, self.enemy)
        
    def rush_detected(self) -> bool:
        return self.enemy_natural_delayed
    
    def enemy_natural_is_built(self) -> bool:
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
                return True
        return False

class Scouting(BaseSquad, DebugMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, workers: Workers, military: Military):
        super().__init__(bot=bot, color=self.random_color(), name="scouting")
        self.bot = bot
        self.enemy = enemy
        self.map = map
        self.workers = workers
        self.military = military
        self.rush_is_detected: bool = False

        self.friendly_territory = Scout("friendly territory", self.bot, enemy)
        self.enemy_territory = Scout("enemy territory", self.bot, enemy)
        self.initial_scout = InitialScout(self.bot, self.map, self.enemy)

        # assign all expansions locations to either friendly or enemy territory
        self.scouting_locations: List[ScoutingLocation] = list()
        for expansion_location in self.bot.expansion_locations_list:
            self.scouting_locations.append(ScoutingLocation(expansion_location))
        nearest_locations_temp = sorted(self.scouting_locations, key=lambda location: (location.position - self.bot.start_location).length)
        enemy_nearest_locations_temp = sorted(self.scouting_locations, key=lambda location: (location.position - self.bot.enemy_start_locations[0]).length)
        for i in range(len(nearest_locations_temp)):
            if not self.enemy_territory.contains_location(nearest_locations_temp[i]):
                self.friendly_territory.add_location(nearest_locations_temp[i])
            if not self.friendly_territory.contains_location(enemy_nearest_locations_temp[i]):
                self.enemy_territory.add_location(enemy_nearest_locations_temp[i])

    def update_visibility(self):
        for location in self.scouting_locations:
            if self.bot.is_visible(location.position):
                location.last_seen = self.bot.time

    async def scout(self, new_damage_taken: dict[int, float]):
        # Update scout unit references
        self.friendly_territory.update_scout(self.military)
        self.enemy_territory.update_scout(self.military)
        self.initial_scout.update_scout(self.workers)

        self.update_visibility()

        await self.initial_scout.move_scout()

        # Move scouts
        await self.friendly_territory.move_scout(new_damage_taken)
        await self.enemy_territory.move_scout(new_damage_taken)

    @property
    def rush_detected(self) -> bool:
        self.rush_is_detected = self.rush_is_detected or self.initial_scout.rush_detected() or self.bot.time < 180 and len(self.bot.enemy_units) > 0 and len(self.bot.enemy_units.closer_than(30, self.bot.start_location)) > 5
        return self.rush_is_detected
