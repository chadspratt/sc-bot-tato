from loguru import logger
from typing import List

from cython_extensions.general_utils import cy_in_pathing_grid_burny
from cython_extensions.geometry import (
    cy_distance_to,
    cy_distance_to_squared,
    cy_towards,
)
from cython_extensions.units_utils import cy_closer_than
from sc2.bot_ai import BotAI
from sc2.data import Race, race_townhalls
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.economy.workers import Workers
from bottato.enums import BuildType
from bottato.map_specifics import MapSpecifics
from bottato.mixins import GeometryMixin
from bottato.squad.squad import Squad
from bottato.tactics import Tactics
from bottato.unit_types import UnitTypes


class InitialScout(Squad, GeometryMixin):
    def __init__(self, bot: BotAI, tactics: Tactics, workers: Workers):
        super().__init__(bot=bot, name="initial_scout")
        self.tactics = tactics
        self.map = tactics.map
        self.enemy = tactics.enemy
        self.intel = tactics.intel
        self.workers = workers

        self.unit: Unit | None = None
        self.midway_point_reached: bool = False
        self.completed: bool = False
        self.enemy_natural_delayed: bool = False
        self.extra_production_detected: bool = False
        self.last_waypoint: Point2 | None = None
        self.do_natural_check: bool = False
        
        # Timing parameters
        self.start_time = 20
        self.initial_scout_complete_time = 120  # Extended time for full scouting
        
        # Scouting waypoints for systematic main base exploration
        self.waypoints: List[Point2] = []
        self.current_waypoint_index: int = 0
        self.waypoints_completed: bool = False
        
        # Initialize waypoints around enemy main
        self._generate_main_base_waypoints()

    def _generate_main_base_waypoints(self):
        """Generate systematic waypoints to explore the enemy main base"""
        enemy_start = self.bot.enemy_start_locations[0]
        
        # Create a systematic grid pattern around the enemy main base
        # Cover the main base area thoroughly
        # base_radius = 15  # Radius around main base to scout
        
        # Add the main base center
        # self.waypoints.append(enemy_start)
        
        # Add waypoints in expanding rings around the main base
        # for radius in [6, 10, 14]:
        for radius in [13]:
            for angle_degrees in range(0, 360, 15):
                import math
                angle_radians = math.radians(angle_degrees)
                x_offset = radius * math.cos(angle_radians)
                y_offset = radius * math.sin(angle_radians)
                waypoint = Point2((enemy_start.x + x_offset, enemy_start.y + y_offset))
                retries = 0
                while not cy_in_pathing_grid_burny(self.bot.game_info.pathing_grid.data_numpy, waypoint) and retries < 5:
                    waypoint = Point2(cy_towards(waypoint, enemy_start, 1))
                    retries += 1
                if retries != 5:
                    self.waypoints.append(waypoint)

        self.original_waypoints = list(self.waypoints)
        
        # Add natural expansion as final waypoint
        # self.waypoints.append(self.map.enemy_natural_position)
        
        logger.debug(f"Generated {len(self.waypoints)} scouting waypoints for enemy main base")

    def update_scout(self):
        if self.bot.time < self.start_time:
            # too early to scout
            return
        if self.completed:
            self.intel.mark_initial_scout_complete()
            if self.unit:
                self.workers.set_as_idle(self.unit)
                self.unit = None
            return
            
        self.unit = self.workers.get_scout(self.scouting_position())
        if self.unit:
            if BuildType.EARLY_EXPANSION in self.intel.enemy_builds_detected and self.intel.enemy_race != Race.Zerg:
                # stop early to proxy vs protoss and terran
                self.completed = True
            elif self.bot.enemy_units.exclude_type(UnitTypes.NON_THREATS).amount > 1:
                # stop if we see 2+ non-worker enemy units, likely not a proxy and worker will die if it sticks around
                self.completed = True
            elif BuildType.WORKER_RUSH in self.intel.enemy_builds_detected:
                self.completed = True


        if self.intel.enemy_race == Race.Zerg:
            self.initial_scout_complete_time = 100

    def record_death(self, unit_tag: int):
        if self.unit and self.unit.tag == unit_tag:
            # scout lost, don't send another
            self.unit = None
            self.completed = True

    def scouting_position(self) -> Point2:
        if self.do_natural_check:
            return self.map.enemy_natural_position
        elif self.waypoints:
            return self.waypoints[0]
        else:
            return self.bot.enemy_start_locations[0]
    
    async def move_scout(self):
        if not self.unit or self.completed:
            return
        
        if self.unit.health_percentage < 0.7 or self.do_natural_check:
            # self.waypoints = [self.map.enemy_natural_position]  # check natural before leaving
            if cy_distance_to(self.unit.position, self.map.enemy_natural_position) < 9:
                if self.intel.enemy_race == Race.Terran and self.bot.enemy_structures(UnitTypeId.COMMANDCENTER).amount < 2:
                    # terran takes longer to start natural?
                    self.completed = self.bot.time > 150
                elif self.bot.time > self.initial_scout_complete_time:
                    self.completed = True
                    self.intel.mark_initial_scout_complete()
                self.do_natural_check = False
        elif self.last_waypoint:
            if cy_distance_to(self.unit.position, self.waypoints[0]) <= 5:
                if self.waypoints[0] == self.last_waypoint:
                    if self.intel.enemy_builds_detected:
                        self.completed = True
                    elif self.bot.time > self.initial_scout_complete_time:
                        self.do_natural_check = True

                self.waypoints.pop(0)
                # Check if we've completed all waypoints
                if len(self.waypoints) == 0:
                    self.waypoints_completed = True
                    self.intel.mark_enemy_main_scouted()
                    self.waypoints = list(self.original_waypoints)  # reset to keep scouting
                    time_for_natural_check = self.bot.time > 70
                    no_enemy_natural = self.bot.enemy_structures(race_townhalls[self.bot.enemy_race]).amount < 2
                    if time_for_natural_check and no_enemy_natural:
                        few_nearby_enemies = len(cy_closer_than(self.bot.enemy_units, 3, self.unit.position)) < 2
                        if few_nearby_enemies:
                            # dip down ramp to check for early natural if not being chased by 2+ enemies
                            self.do_natural_check = True
        else:
            # find initial waypoint
            i = 0
            while i < len(self.waypoints):
                # remove waypoints as they are checked
                if cy_distance_to(self.unit.position, self.waypoints[i]) <= 5:
                    if not self.waypoints_completed and len(self.waypoints) == len(self.original_waypoints):
                        # first waypoint reached, reorder original waypoints to start from this one
                        self.original_waypoints = self.original_waypoints[i:] + self.original_waypoints[:i]
                        self.waypoints = list(self.original_waypoints)
                        self.waypoints.pop(0)
                        self.last_waypoint = self.waypoints[-1]
                        break
                i += 1
            
        # for waypoint in self.waypoints:
        #     self.bot.client.debug_box2_out(self.convert_point2_to_3(waypoint))
        midway_point = MapSpecifics.worker_scout_midway_point(self.bot)
        if midway_point and not self.midway_point_reached:
            if cy_distance_to_squared(self.unit.position, midway_point) > 100:
                self.unit.move(midway_point)
                return
            else:
                self.midway_point_reached = True
            
        # Move to current waypoint
        scouting_position = self.scouting_position()
        self.workers.update_target_position(self.unit, scouting_position)
        self.unit.move(scouting_position)