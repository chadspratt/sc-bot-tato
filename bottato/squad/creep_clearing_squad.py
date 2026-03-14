from __future__ import annotations

import math
from typing import Dict, Set

from cython_extensions.geometry import (
    cy_angle_to,
    cy_distance_to,
    cy_distance_to_squared,
    cy_towards,
)
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.units import Units

from bottato.enums import ExpansionSelection, UnitMicroType
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.micro_factory import MicroFactory
from bottato.mixins import timed_async
from bottato.squad.hunting_squad import HuntingSquad
from bottato.tactics import Tactics

# Radius around an expansion position to patrol for creep tumors
EXPANSION_PATROL_RADIUS = 10.0
# Angle increment per call when circling an expansion (radians)
CIRCLE_STEP = 0.35
# How close is "close enough" to mark a patrol waypoint as reached
WAYPOINT_REACHED_DISTANCE_SQ = 4.0
# If stuck near waypoint for this many seconds, advance to next
STUCK_TIMEOUT = 5.0
# Max distance from raven to non-raven squad members before raven prioritises regrouping
RAVEN_MAX_LEASH_SQ = 11.0 ** 2  # sight range ~11 for raven


class CreepClearingSquad(HuntingSquad):
    """Specialized hunting squad that focuses on clearing creep around expansions.

    Priorities:
    1. Keep the next unused expansion clear of creep by circling it to spot tumors.
    2. Clear creep edges first — prioritise tumors closest to friendly structures.
    3. Raven stays within view range of ground squad members for continuous detection.
    """

    def __init__(
        self,
        bot: BotAI,
        tactics: Tactics,
        name: str,
        color: tuple[int, int, int],
    ):
        super().__init__(bot, tactics, name, color)
        self.patrol_angle: float = 0.0
        self.current_waypoint: Point2 | None = None
        self.waypoint_reached_time: float = 0.0

    def __repr__(self):
        return f"CreepClearingSquad({self.name},{len(self.units)})"

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _get_priority_expansion(self) -> Point2 | None:
        """Return the position of the next expansion we want to keep creep-free."""
        return self.tactics.map.get_next_expansion(ExpansionSelection.AWAY_FROM_ENEMY)

    def _get_ground_units(self) -> Units:
        return self.units.filter(lambda u: u.type_id != UnitTypeId.RAVEN)

    def _get_raven(self) -> Units:
        return self.units.of_type(UnitTypeId.RAVEN)

    def _next_patrol_waypoint(self, center: Point2) -> Point2:
        """Advance the patrol angle and return the next point on the circle."""
        self.patrol_angle = (self.patrol_angle + CIRCLE_STEP) % (2 * math.pi)
        offset = Point2((
            math.cos(self.patrol_angle) * EXPANSION_PATROL_RADIUS,
            math.sin(self.patrol_angle) * EXPANSION_PATROL_RADIUS,
        ))
        return center + offset

    def _sort_targets_by_edge_priority(self, targets: Units) -> list:
        """Sort creep targets so those closest to friendly structures come first."""
        structures = self.bot.townhalls
        if not structures:
            return list(targets)
        return sorted(
            targets,
            key=lambda t: min(
                cy_distance_to_squared(t.position, s.position)
                for s in structures
            ),
        )

    # ------------------------------------------------------------------
    # main loop override
    # ------------------------------------------------------------------

    @timed_async
    async def hunt(self, target_types: Set[UnitTypeId]):
        if not self.units:
            return
        self.had_units = True

        ground_units = self._get_ground_units()
        ravens = self._get_raven()

        # --- find creep targets ---
        all_targets = self.enemy.get_recent_enemies().filter(
            lambda u: u.type_id in target_types
        )
        safe_targets = all_targets.filter(
            lambda u: self.bot.time - self.unsafe_targets.get(u.tag, 0) > 20
        )
        if not safe_targets:
            safe_targets = all_targets.filter(
                lambda u: self.bot.time - self.unsafe_targets.get(u.tag, 0) > 5
            )

        # --- priority 2: edge-first — sort by proximity to friendly structures ---
        if safe_targets:
            sorted_targets = self._sort_targets_by_edge_priority(safe_targets)
            target = sorted_targets[0]

            # Reset patrol state while actively clearing
            self.next_location = None
            self.closest_distance_to_next_location = float('inf')
            self.current_waypoint = None

            # Send ground units to the highest-priority target
            for unit in ground_units:
                micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
                destination = Point2(
                    cy_towards(
                        target.position,
                        unit.position,
                        max(0, cy_distance_to(target.position, unit.position) - 1),
                    )
                )
                if await micro.move(unit, destination) == UnitMicroType.RETREAT:
                    self.unsafe_targets[target.tag] = self.bot.time

            # Raven keeps ground units in view instead of running independently
            await self._raven_follow_squad(ravens, ground_units)
            return

        # --- priority 1: patrol next unused expansion ---
        expansion_pos = self._get_priority_expansion()
        if expansion_pos is not None:
            await self._patrol_expansion(expansion_pos, ground_units, ravens)
            return

        # --- fallback: default scouting behaviour from parent ---
        await self._fallback_scout(ground_units, ravens)

    # ------------------------------------------------------------------
    # patrol logic
    # ------------------------------------------------------------------

    async def _patrol_expansion(
        self,
        expansion_pos: Point2,
        ground_units: Units,
        ravens: Units,
    ):
        """Circle around the expansion to uncover creep tumors."""
        if self.current_waypoint is None:
            self.current_waypoint = self._next_patrol_waypoint(expansion_pos)
            self.waypoint_reached_time = 0.0

        # Check if we arrived at current waypoint
        if ground_units:
            center = ground_units.center
        else:
            center = ravens.center if ravens else self.units.center
        dist_sq = cy_distance_to_squared(center, self.current_waypoint)

        if dist_sq < WAYPOINT_REACHED_DISTANCE_SQ:
            # Arrived — advance to next waypoint
            self.current_waypoint = self._next_patrol_waypoint(expansion_pos)
            self.waypoint_reached_time = 0.0
        else:
            # Track stuck detection
            if self.waypoint_reached_time == 0.0:
                self.waypoint_reached_time = self.bot.time
            elif self.bot.time - self.waypoint_reached_time > STUCK_TIMEOUT:
                # Can't reach waypoint, skip to next
                self.current_waypoint = self._next_patrol_waypoint(expansion_pos)
                self.waypoint_reached_time = 0.0

        for unit in ground_units:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
            await micro.harass(unit, self.current_waypoint)

        await self._raven_follow_squad(ravens, ground_units)

    # ------------------------------------------------------------------
    # raven behaviour — stay close to squad for detection coverage
    # ------------------------------------------------------------------

    async def _raven_follow_squad(self, ravens: Units, ground_units: Units):
        """Move the raven to keep ground squad members within its detection range."""
        if not ravens:
            return
        if not ground_units:
            # No ground units — raven does default behaviour
            for raven in ravens:
                micro: BaseUnitMicro = MicroFactory.get_unit_micro(raven)
                if self.current_waypoint:
                    await micro.harass(raven, self.current_waypoint)
            return

        squad_center = ground_units.center
        for raven in ravens:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(raven)
            dist_sq = cy_distance_to_squared(raven.position, squad_center)

            if dist_sq > RAVEN_MAX_LEASH_SQ:
                # Too far — move towards squad
                regroup_pos = Point2(
                    cy_towards(squad_center, raven.position, raven.sight_range - 2)
                )
                await micro.move(raven, regroup_pos)
            else:
                # Close enough — slightly lead the squad towards their destination
                if self.current_waypoint:
                    lead_pos = Point2(
                        cy_towards(
                            self.current_waypoint,
                            raven.position,
                            min(raven.sight_range - 2, cy_distance_to(self.current_waypoint, raven.position)),
                        )
                    )
                    await micro.harass(raven, lead_pos)
                else:
                    # Stay with squad center
                    await micro.move(raven, squad_center)

    # ------------------------------------------------------------------
    # fallback — scout friendly-side expansion locations
    # ------------------------------------------------------------------

    async def _fallback_scout(self, ground_units: Units, ravens: Units):
        """When nothing to clear and no expansion to patrol, scout friendly expansions."""
        scout_locations = self.tactics.map.expansion_orders[ExpansionSelection.AWAY_FROM_ENEMY]
        location_count = len(scout_locations) // 2 + 1
        self.next_location = sorted(scout_locations[:location_count], key=lambda loc: loc.last_seen)[0]

        for unit in ground_units:
            micro: BaseUnitMicro = MicroFactory.get_unit_micro(unit)
            await micro.harass(unit, self.next_location.scouting_position)

        await self._raven_follow_squad(ravens, ground_units)

        # Mark location as visited if close enough or stuck
        distance_to_next = cy_distance_to_squared(
            self.units.center, self.next_location.scouting_position
        )
        if distance_to_next < self.closest_distance_to_next_location:
            self.closest_distance_to_next_location = distance_to_next
            self.time_of_closest_distance = self.bot.time
        if distance_to_next < 2 or (
            self.closest_distance_to_next_location < 30
            and self.bot.time - self.time_of_closest_distance > 5
        ):
            self.next_location.last_seen = self.bot.time
            self.next_location = None
            self.closest_distance_to_next_location = float('inf')
