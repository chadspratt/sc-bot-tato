from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from .squad import BaseSquad
from .enemy import Enemy


class ScoutingLocation:
    def __init__(self, position: Point2):
        self.position: Point2 = position
        self.scouted_units: Units = []
        self.last_seen: int = None

    def __repr__(self) -> str:
        return f"ScoutingLocation({self.position}, {self.last_seen})"


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
        self.scouting_assignments: dict[Unit, ScoutingLocation] = {}
        self.units: Units = []
        self.last_scouted = {}
        self.nearest_locations: List[ScoutingLocation] = list()
        self.enemy_nearest_locations: List[ScoutingLocation] = list()
        self.nearest_index = 0
        self.enemy_nearest_index = 0
        for expansion_location in self.bot.expansion_locations_list:
            self.scouting_locations.append(ScoutingLocation(expansion_location))
        nearest_locations_temp = sorted(self.scouting_locations, key=lambda location: (location.position - self.bot.start_location).length)
        enemy_nearest_locations_temp = sorted(self.scouting_locations, key=lambda location: (location.position - self.bot.enemy_start_locations[0]).length)
        # self.enemy_nearest_locations.append(self.bot.enemy_start_locations[0])
        for i in range(len(nearest_locations_temp)):
            if nearest_locations_temp[i] not in self.enemy_nearest_locations:
                self.nearest_locations.append(nearest_locations_temp[i])
            if enemy_nearest_locations_temp[i] not in self.nearest_locations:
                self.enemy_nearest_locations.append(enemy_nearest_locations_temp[i])

        logger.debug(f"nearest locations {self.nearest_locations}")
        logger.debug(f"enemy locations {self.enemy_nearest_locations}")

    def report(self):
        logger.info("I'm scouting damnit")

    @property
    def scouts_needed(self):
        return 2 - len(self.units)

    def recruit(self, unit: Unit):
        logger.info(f"Assigning scout {unit}")
        self.units.append(unit)

    def update_visibility(self):
        for location in self.scouting_locations:
            if self.bot.is_visible(location.position):
                location.last_seen = self.bot.time

    def move_scouts(self, new_damage_taken: dict[int, float]):
        if len(self.units) > 0:
            scout: Unit = self.units[0]
            logger.info(f"first scout {scout}")
            self.enemy_nearest_index = self.move_scout(scout, self.enemy_nearest_locations,
                                                       self.enemy_nearest_index, new_damage_taken)
            self.bot.client.move_camera(scout)

        if len(self.units) > 1:
            scout: Unit = self.units[1]
            logger.info(f"second scout {scout}")
            self.nearest_index = self.move_scout(scout, self.nearest_locations,
                                                 self.nearest_index, new_damage_taken)

    def move_scout(self, scout: Unit,
                   locations: list[ScoutingLocation],
                   location_index: int,
                   new_damage_taken: dict[int, float]) -> int:
        assignment: ScoutingLocation = (
            self.scouting_assignments[scout]
            if scout in self.scouting_assignments
            else locations[location_index]
        )
        logger.info(f"scout assignment {assignment}")

        if scout.health_percentage < 0.75:
            if scout.is_flying:
                threats = [enemy_unit for enemy_unit in self.bot.all_enemy_units
                           if enemy_unit.can_attack_air
                           and enemy_unit.air_range + 1 > scout.distance_to(enemy_unit)]
            else:
                threats = [enemy_unit for enemy_unit in self.bot.all_enemy_units
                           if enemy_unit.can_attack_ground
                           and enemy_unit.ground_range + 1 > scout.distance_to(enemy_unit)]
            retreat_vector = Point2([0, 0])
            if threats:
                for threat in threats:
                    retreat_vector += scout.position - threat.position
            else:
                retreat_vector = self.bot.game_info.map_center
            scout.move(scout.position + retreat_vector.normalized)
            return location_index

        if scout.weapon_cooldown == 0:
            targets = self.bot.all_enemy_units.in_attack_range_of(scout)
            if targets:
                target = targets.sorted(key=lambda enemy_unit: enemy_unit.health).first
                scout.attack(target)
                return location_index

        # move to next location if taking damage
        next_index = location_index
        if scout.tag in new_damage_taken:
            next_index = (next_index + 1) % len(locations)
            assignment: ScoutingLocation = locations[next_index]

        while assignment.last_seen and self.bot.time - assignment.last_seen < 10:
            logger.info(f"scout location {assignment}")
            next_index = (next_index + 1) % len(locations)
            if next_index == location_index:
                # full cycle, none need scouting
                break
            assignment: ScoutingLocation = locations[next_index]
        location_index = next_index
        logger.info(f"updated scout assignment {assignment}")

        scout.move(assignment.position)
        self.scouting_assignments[scout] = assignment
        return location_index
