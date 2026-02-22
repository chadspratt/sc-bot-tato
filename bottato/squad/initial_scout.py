from loguru import logger
from typing import List

from cython_extensions.general_utils import cy_in_pathing_grid_burny
from cython_extensions.geometry import cy_distance_to, cy_towards
from cython_extensions.units_utils import cy_closer_than
from sc2.bot_ai import BotAI
from sc2.data import Race, race_townhalls
from sc2.ids.ability_id import AbilityId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.economy.workers import Workers
from bottato.enemy import Enemy
from bottato.enums import BuildType
from bottato.map.map import Map
from bottato.mixins import GeometryMixin
from bottato.squad.enemy_intel import EnemyIntel
from bottato.squad.formation import Formation
from bottato.squad.squad import Squad
from bottato.unit_reference_helper import UnitReferenceHelper


class InitialScout(Squad, GeometryMixin):
    def __init__(self, bot: BotAI, map: Map, enemy: Enemy, intel: EnemyIntel):
        super().__init__(bot=bot, name="initial_scout")
        self.map = map
        self.enemy = enemy
        self.intel = intel

        self.unit: Unit | None = None
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

    def update_scout(self, workers: Workers):
        if self.bot.time < self.start_time:
            # too early to scout
            return
        # if self.intel.enemy_builds_detected:
        #     self.completed = True
        #     self.intel.mark_initial_scout_complete()
            
        if self.unit:
            try:
                self.unit = UnitReferenceHelper.get_updated_unit_reference(self.unit)
            except UnitReferenceHelper.UnitNotFound:
                self.unit = None
                # scout lost, don't send another
                self.completed = True
                return
            if BuildType.EARLY_EXPANSION in self.intel.enemy_builds_detected:
                self.completed = True

            if self.completed:
                workers.set_as_idle(self.unit)
                self.intel.mark_initial_scout_complete()
                self.unit = None
                return
                
        if not self.unit and not self.completed:
            # Get the first waypoint as initial target
            target = self.waypoints[0] if self.waypoints else self.map.enemy_natural_position
            self.unit = workers.get_scout(target)

        if self.intel.enemy_race == Race.Zerg:
            self.initial_scout_complete_time = 100
    
    async def move_scout(self):
        # if self.bot.time > self.initial_scout_complete_time + 20:
        #     self.completed = True
        #     self.intel.mark_initial_scout_complete()
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
            
        # Move to current waypoint
        if self.do_natural_check:
            self.unit.move(self.map.enemy_natural_position)
        elif self.waypoints:
            self.unit.move(self.waypoints[0])