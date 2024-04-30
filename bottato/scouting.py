from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from .squad import BaseSquad
from .enemy import Enemy
from .mixins import UnitReferenceMixin
from .micro.base import BaseUnitMicro
from .micro.micro_factory import MicroFactory


class ScoutingLocation:
    def __init__(self, position: Point2):
        self.position: Point2 = position
        self.scouted_units: Units = []
        self.last_seen: int = None

    def __repr__(self) -> str:
        return f"ScoutingLocation({self.position}, {self.last_seen})"


class Scout(UnitReferenceMixin):
    def __init__(self, name, bot: BotAI):
        self.name: str = name
        self.bot: BotAI = bot
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

    def update_scout(self, new_damage_taken: dict[int, float]):
        if self.unit:
            try:
                self.unit = self.get_updated_unit_reference(self.unit)
                logger.info(f"{self.name} scout {self.unit}")
                self.move_scout(new_damage_taken)
            except self.UnitNotFound:
                self.unit = None
                pass

    def move_scout(self, new_damage_taken: dict[int, float]):
        assignment: ScoutingLocation = self.scouting_locations[self.scouting_locations_index]
        logger.info(f"scout {self.unit} previous assignment: {assignment}")

        micro: BaseUnitMicro = MicroFactory.get_unit_micro(self.unit, self.bot)

        # move to next location if taking damage
        next_index = self.scouting_locations_index
        if self.unit.tag in new_damage_taken:
            next_index = (next_index + 1) % len(self.scouting_locations)
            assignment: ScoutingLocation = self.scouting_locations[next_index]
            logger.info(f"scout {self.unit} took damage, changing assignment")

        while assignment.last_seen and self.bot.time - assignment.last_seen < 10:
            next_index = (next_index + 1) % len(self.scouting_locations)
            if next_index == self.scouting_locations_index:
                # full cycle, none need scouting
                break
            assignment: ScoutingLocation = self.scouting_locations[next_index]
        self.scouting_locations_index = next_index
        logger.info(f"scout {self.unit} new assignment: {assignment}")

        micro.scout(assignment.position)


class Scouting(BaseSquad):
    """finds enemy town halls, and tracks last time it saw them.
    Must find enemy. Includes structures and units.
    Must cover map
    uses single unit "squads"
    Initially looks for base positions
    assign first two reapers as they are built to immediately start scouting
    """
    def __init__(self, bot: BotAI, enemy: Enemy):
        self.bot = bot
        self.enemy = enemy
        self.scouting_locations: List[ScoutingLocation] = list()
        self.units: Units = []

        self.friendly_territory = Scout("friendly territory", self.bot)
        self.enemy_territory = Scout("enemy territory", self.bot)

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

        logger.info(f"friendly_territory {self.friendly_territory}")
        logger.info(f"enemy_territory {self.enemy_territory}")

    @property
    def scouts_needed(self):
        return self.friendly_territory.scouts_needed + self.enemy_territory.scouts_needed

    def recruit(self, unit: Unit):
        if self.enemy_territory.scouts_needed > 0:
            logger.info(f"Assigning scout {unit} to enemy_territory")
            self.enemy_territory.unit = unit
        elif self.friendly_territory.scouts_needed > 0:
            logger.info(f"Assigning scout {unit} to friendly_territory")
            self.friendly_territory.unit = unit

    def update_visibility(self):
        for location in self.scouting_locations:
            if self.bot.is_visible(location.position):
                location.last_seen = self.bot.time

    def move_scouts(self, new_damage_taken: dict[int, float]):
        self.friendly_territory.update_scout(new_damage_taken)
        self.enemy_territory.update_scout(new_damage_taken)
