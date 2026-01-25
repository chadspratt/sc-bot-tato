from typing import Dict, List
from loguru import logger
from collections import deque

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bottato.mixins import GeometryMixin, timed
from bottato.squad.enemy_squad import EnemySquad
from bottato.unit_types import UnitTypes
from bottato.unit_reference_helper import UnitReferenceHelper


class Enemy(GeometryMixin):
    unit_probably_moved_seconds = 10
    unit_may_not_exist_seconds = 600
    enemy_squad_counter = 0
    frames_of_movement_history = 5

    def __init__(self, bot: BotAI):
        self.bot: BotAI = bot
        # probably need to refresh this
        self.enemies_in_view: Units = Units([], bot)
        self.enemies_out_of_view: Units = Units([], bot)
        self.enemies_killed: List[tuple[Unit, float]] = []
        self.new_units: Units = Units([], bot)
        self.first_seen: Dict[int, float] = {}
        self.last_seen: Dict[int, float] = {}
        self.last_seen_step: Dict[int, int] = {}
        self.last_seen_position: Dict[int, Point2] = {}
        self.last_seen_positions: Dict[int, deque] = {}
        self.predicted_position: Dict[int, Point2] = {}
        self.predicted_frame_vector: Dict[int, Point2] = {}
        self.squads_by_unit_tag: Dict[int, EnemySquad] = {}
        self.all_seen: Dict[UnitTypeId, set[int]] = {}
        self.attack_range_squared_cache: Dict[UnitTypeId, Dict[float, Dict[UnitTypeId, float]]] = {}
        self.unit_distance_squared_cache: Dict[int, Dict[int, float]] = {}
        self.suddenly_seen_units: Units = Units([], bot)

    @timed
    def update_references(self):
        self.unit_distance_squared_cache.clear()

        new_visible_enemies: Units = self.bot.enemy_units + self.bot.enemy_structures
        
        self.detect_suddenly_seen_units(new_visible_enemies)
        self.update_out_of_view()
        self.set_last_seen_for_visible(new_visible_enemies)
        self.add_new_out_of_view()

        self.enemies_in_view = new_visible_enemies

    @timed
    def update_out_of_view(self):
        for enemy_unit in self.enemies_out_of_view:
            time_since_last_seen = self.bot.time - self.last_seen[enemy_unit.tag]
            if enemy_unit.is_structure and self.is_visible(enemy_unit.position, enemy_unit.radius):
                self.enemies_out_of_view.remove(enemy_unit)
            elif enemy_unit.tag in UnitReferenceHelper.units_by_tag or time_since_last_seen > self.unit_may_not_exist_seconds:
                self.enemies_out_of_view.remove(enemy_unit)
            else:
                # assume unit continues in same direction
                self.last_seen_positions[enemy_unit.tag].append(None)
                new_prediction = self.get_predicted_position(enemy_unit, 0)
                # move projection to edge of visibility
                if self.is_visible(new_prediction, enemy_unit.radius):
                    if self.last_seen_position[enemy_unit.tag] != new_prediction:
                        predicted_vector = (new_prediction - self.last_seen_position[enemy_unit.tag]).normalized
                    elif self.bot.units:
                        closest_friendly_unit = self.closest_unit_to_unit(enemy_unit, self.bot.units)
                        predicted_vector = (new_prediction - closest_friendly_unit.position).normalized
                    else:
                        continue
                    position_found = False
                    # check both directions along predicted vector
                    # checking forward is useful when enemy unit is running away
                    # checking backward is useful when friendly unit is running away
                    # use whichever direction gets out of vision first
                    new_prediction1 = new_prediction + predicted_vector
                    new_prediction2 = new_prediction - predicted_vector
                    while not position_found:
                        if not self.is_visible(new_prediction1, enemy_unit.radius):
                            position_found = True
                            new_prediction = new_prediction1
                            break
                        if not self.is_visible(new_prediction2, enemy_unit.radius):
                            position_found = True
                            new_prediction = new_prediction2
                            break
                        new_prediction1 += predicted_vector
                        new_prediction2 -= predicted_vector
                self.predicted_position[enemy_unit.tag] = new_prediction

                if time_since_last_seen <= self.unit_probably_moved_seconds:
                    self.bot.client.debug_box2_out(
                        self.convert_point2_to_3(self.predicted_position[enemy_unit.tag], self.bot),
                        half_vertex_length=enemy_unit.radius,
                        color=(255, 0, 0)
                    )
    
    @timed
    def set_last_seen_for_visible(self, visible_enemies: Units):
        for enemy_unit in visible_enemies:
            self.bot.client.debug_box2_out(
                enemy_unit,
                half_vertex_length=enemy_unit.radius,
                color=(255, 0, 0)
            )
            self.last_seen[enemy_unit.tag] = self.bot.time
            self.last_seen_step[enemy_unit.tag] = self.bot.state.game_loop
            self.last_seen_position[enemy_unit.tag] = enemy_unit.position
            if enemy_unit.tag not in self.last_seen_positions:
                self.last_seen_positions[enemy_unit.tag] = deque(maxlen=self.frames_of_movement_history)
            self.last_seen_positions[enemy_unit.tag].append(enemy_unit.position)
            self.predicted_position[enemy_unit.tag] = enemy_unit.position
            self.predicted_frame_vector[enemy_unit.tag] = self.get_average_movement_per_step(self.last_seen_positions[enemy_unit.tag])
            if enemy_unit.tag not in self.first_seen:
                self.first_seen[enemy_unit.tag] = self.bot.time
                self.all_seen.setdefault(enemy_unit.type_id, set()).add(enemy_unit.tag)

    @timed
    def add_new_out_of_view(self):
        # add not visible to out_of_view
        for enemy_unit in self.enemies_in_view:
            if enemy_unit.tag not in UnitReferenceHelper.units_by_tag:
                if enemy_unit.type_id not in (UnitTypeId.LARVA, UnitTypeId.EGG):
                    added = False
                    if enemy_unit.is_structure:
                        for out_of_view_unit in self.enemies_out_of_view:
                            if out_of_view_unit.type_id == enemy_unit.type_id and out_of_view_unit.position == enemy_unit.position:
                                added = True
                                # tags aren't consistent so check position to avoid duplicates
                                break
                    if not added:
                        self.enemies_out_of_view.append(enemy_unit)
                        self.predicted_position[enemy_unit.tag] = self.get_predicted_position(enemy_unit, 0)
                        self.last_seen_positions[enemy_unit.tag].append(None)
                        self.bot.client.debug_box2_out(
                            enemy_unit,
                            half_vertex_length=enemy_unit.radius,
                            color=(255, 0, 0)
                        )

    def is_visible(self, position: Point2, radius: float) -> bool:
        positions_to_check = [
            position,
            Point2((position.x - radius, position.y)),
            Point2((position.x + radius, position.y)),
            Point2((position.x, position.y - radius)),
            Point2((position.x, position.y + radius)),
            Point2((position.x - radius, position.y - radius)),
            Point2((position.x - radius, position.y + radius)),
            Point2((position.x + radius, position.y - radius)),
            Point2((position.x + radius, position.y + radius)),
        ]
        for pos in positions_to_check:
            if self.bot.is_visible(pos):
                return True
        return False

    @timed
    def get_predicted_position(self, unit: Unit, seconds_ahead: float) -> Point2:
        if unit.type_id in (UnitTypeId.COLLAPSIBLEROCKTOWERDEBRIS,):
            return unit.position
        if unit.age > 0 and unit not in self.enemies_out_of_view:
            return unit.position
        last_predicted_position = self.predicted_position[unit.tag] if unit.tag in self.predicted_position else self.last_seen_position[unit.tag]
        frame_vector = self.predicted_frame_vector[unit.tag]
        return self.predict_future_unit_position(unit, last_predicted_position, seconds_ahead, self.bot, frame_vector=frame_vector)
        
    def predict_future_unit_position(self,
                                     unit: Unit,
                                     last_predicted_position: Point2,
                                     seconds_ahead: float,
                                     bot: BotAI,
                                     check_pathable: bool = True,
                                     frame_vector: Point2 | None = None
                                     ) -> Point2:
        time_since_last_frame = 4 / 22.4
        if unit.is_structure:
            return last_predicted_position
        unit_speed: float
        forward_unit_vector: Point2
        max_speed = unit.calculate_speed()
        if frame_vector is not None:
            speed_per_frame = frame_vector.length
            if speed_per_frame == 0:
                return last_predicted_position
            unit_speed = min(speed_per_frame * 22.4, max_speed)
            forward_unit_vector = frame_vector.normalized
        else:
            unit_speed = max_speed
            forward_unit_vector = GeometryMixin.apply_rotation(unit.facing, Point2([0, 1]))

        remaining_distance = unit_speed * (seconds_ahead + time_since_last_frame)
        if not check_pathable:
            return last_predicted_position + forward_unit_vector * remaining_distance

        future_position = last_predicted_position
        while True:
            if remaining_distance < 1:
                forward_unit_vector *= remaining_distance
            potential_position = future_position + forward_unit_vector
            if not bot.in_pathing_grid(potential_position):
                return future_position

            future_position = potential_position

            remaining_distance -= 1
            if remaining_distance <= 0:
                return future_position

    @timed
    def get_average_movement_per_step(self, recent_positions: deque):
        sum: Point2 = Point2((0, 0))
        sample_count = len(recent_positions)
        if sample_count <= 1:
            return sum
        elif sample_count > 2 and recent_positions[-1] == recent_positions[-2] == recent_positions[-3]:
            # last 3 positions were all the same
            return sum
        start: Point2 = recent_positions[0]
        i = 1
        actual_sample_count = 0
        while i < sample_count:
            end: Point2 = recent_positions[i]
            i += 1
            if start is None or end is None:
                start = end
                continue
            sum += end - start
            start = end
            actual_sample_count += 1
        if actual_sample_count > 0:
            sum /= actual_sample_count
        return sum

    def record_death(self, unit_tag):
        found = False
        for enemy_unit in self.enemies_out_of_view:
            if enemy_unit.tag == unit_tag:
                found = True
                self.enemies_out_of_view.remove(enemy_unit)
                self.enemies_killed.append((enemy_unit, self.bot.time))
                break
        if not found:
            for enemy_unit in self.enemies_in_view:
                if enemy_unit.tag == unit_tag:
                    found = True
                    self.enemies_in_view.remove(enemy_unit)
                    self.enemies_killed.append((enemy_unit, self.bot.time))
                    break
        if found:
            del self.first_seen[unit_tag]
            # del self.last_seen_position[unit_tag]
            if unit_tag in self.predicted_position:
                del self.predicted_position[unit_tag]

    all_enemies_cache: Dict[float, Units] = {}
    @timed
    def threats_to_friendly_unit(self, friendly_unit: Unit, attack_range_buffer=0, visible_only=False, first_only: bool = False) -> Units:
        enemies: Units
        if visible_only:
            enemies = self.enemies_in_view
        else:
            if self.bot.time not in self.all_enemies_cache:
                self.all_enemies_cache.clear()
                self.all_enemies_cache[self.bot.time] = self.enemies_in_view + self.recent_out_of_view()
            enemies = self.all_enemies_cache[self.bot.time]
        return self.threats_to(friendly_unit, enemies, attack_range_buffer, first_only=first_only)
    
    def in_friendly_attack_range(self, friendly_unit: Unit, targets: Units | None = None, attack_range_buffer:float=0) -> Units:
        candidates = targets if targets else self.enemies_in_view
        in_range = self.in_attack_range(friendly_unit, candidates, attack_range_buffer)
        return in_range
    
    def in_enemy_attack_range(self, enemy_unit: Unit, targets: Units | None = None, attack_range_buffer: float=0) -> Units:
        candidates = targets if targets else self.bot.units + self.bot.structures
        in_range = self.in_attack_range(enemy_unit, candidates, attack_range_buffer)
        return in_range
    
    @timed
    def in_attack_range(self, unit: Unit, targets: Units, attack_range_buffer: float=0, first_only: bool = False) -> Units:
        in_range = Units([], self.bot)

        targets = targets.filter(lambda u: UnitTypes.can_attack_target(unit, u)
                                and u.armor < 10
                                and BuffId.NEURALPARASITE not in u.buffs)

        for enemy_unit in targets:
            attack_range_squared = self.get_attack_range_with_buffer_squared(unit, enemy_unit, attack_range_buffer)
            distance_squared = self.distance_squared(unit, enemy_unit, self.predicted_position)

            if distance_squared <= attack_range_squared:
                in_range.append(enemy_unit)
                if first_only:
                    break

        return in_range

    unseen_threat_types: set[UnitTypeId] = set((
        UnitTypeId.SIEGETANKSIEGED,
        UnitTypeId.TEMPEST,
        UnitTypeId.LURKERMPBURROWED
    ))
    @timed
    def threats_to(self, unit: Unit, attackers: Units, attack_range_buffer=0, first_only: bool = False) -> Units:
        in_range = Units([], self.bot)

        attackers = attackers.filter(lambda u: UnitTypes.can_attack_target(u, unit)
                                    and (attack_range_buffer > 0 or u.age == 0 or u.type_id in self.unseen_threat_types))

        for enemy_unit in attackers:
            buffer = 1 if enemy_unit.is_structure else attack_range_buffer
            attack_range_squared = self.get_attack_range_with_buffer_squared(enemy_unit, unit, buffer)
            distance_squared = self.distance_squared(unit, enemy_unit, self.predicted_position)

            if distance_squared <= attack_range_squared:
                in_range.append(enemy_unit)
                if first_only:
                    break

        return in_range

    @timed
    def threat_in_attack_range(self, friendly_unit: Unit, enemies: Units, attack_range_buffer=0.0, first_only: bool = False) -> Units:
        in_range = Units([], self.bot)

        enemies = enemies.filter(lambda u: (
                                            UnitTypes.can_attack_target(u, friendly_unit)
                                            and UnitTypes.can_attack_target(friendly_unit, u)
                                            and u.age == 0
                                            and u.armor < 10
                                            and BuffId.NEURALPARASITE not in u.buffs
                                        ))

        for enemy_unit in enemies:
            attack_range_squared = max(
                self.get_attack_range_with_buffer_squared(enemy_unit, friendly_unit, attack_range_buffer),
                self.get_attack_range_with_buffer_squared(friendly_unit, enemy_unit, attack_range_buffer)
            )
            distance_squared = self.distance_squared(friendly_unit, enemy_unit, self.predicted_position)

            if distance_squared <= attack_range_squared:
                in_range.append(enemy_unit)
                if first_only:
                    break

        return in_range

    def get_attack_range_with_buffer_squared(self, attacker: Unit, target: Unit, attack_range_buffer: float) -> float:
        # pre-calculated attack ranges with different buffers, for gauging whether units are in range by comparing to their distance squared
        try:
            return self.attack_range_squared_cache[attacker.type_id][attack_range_buffer][target.type_id]
        except KeyError:
            if attacker.type_id not in self.attack_range_squared_cache:
                self.attack_range_squared_cache[attacker.type_id] = {}
            if attack_range_buffer not in self.attack_range_squared_cache[attacker.type_id]:
                self.attack_range_squared_cache[attacker.type_id][attack_range_buffer] = {}
            base_range = UnitTypes.range_vs_target(attacker, target)
            if base_range == 0:
                self.attack_range_squared_cache[attacker.type_id][attack_range_buffer][target.type_id] = 0.0
            else:
                self.attack_range_squared_cache[attacker.type_id][attack_range_buffer][target.type_id] = (base_range + attack_range_buffer + attacker.radius + target.radius) ** 2
            return self.attack_range_squared_cache[attacker.type_id][attack_range_buffer][target.type_id]

    @timed
    def threats_to_repairer(self, friendly_unit: Unit, attack_range_buffer: float=2) -> Units:
        threats = Units([enemy_unit for enemy_unit in self.enemies_in_view
                         if UnitTypes.target_in_range(enemy_unit, friendly_unit, attack_range_buffer)],
                        self.bot)
        range_limits: Dict[UnitTypeId, float] = {}
        for enemy_unit in self.recent_out_of_view():
            if enemy_unit.type_id not in range_limits:
                enemy_attack_range = UnitTypes.ground_range(enemy_unit)
                if enemy_attack_range == 0.0:
                    range_limits[enemy_unit.type_id] = 0
                else:
                    range_limits[enemy_unit.type_id] = (enemy_attack_range + attack_range_buffer) ** 2
            range_limit = range_limits[enemy_unit.type_id]
            if range_limit == 0.0:
                continue
            if self.distance_squared(friendly_unit, enemy_unit, self.predicted_position) < range_limit:
                threats.append(enemy_unit)
        return threats

    def get_enemies(self) -> Units:
        return self.enemies_in_view + self.recent_out_of_view()

    non_army_unit_types = {
        UnitTypeId.SCV,
        UnitTypeId.MULE,
        UnitTypeId.DRONE,
        UnitTypeId.PROBE,
        UnitTypeId.OVERLORD,
        UnitTypeId.OVERSEER,
        UnitTypeId.OBSERVER,
        UnitTypeId.LARVA,
        UnitTypeId.EGG,
    }

    non_army_non_scout_unit_types = {
        UnitTypeId.SCV,
        UnitTypeId.MULE,
        UnitTypeId.DRONE,
        UnitTypeId.PROBE,
        UnitTypeId.LARVA,
        UnitTypeId.EGG,
    }

    def get_army(self, include_scouts: bool = False, seconds_since_killed: float = 0) -> Units:
        excluded_types = self.non_army_non_scout_unit_types if include_scouts else self.non_army_unit_types
        enemies = (self.enemies_in_view + self.enemies_out_of_view)
        if seconds_since_killed > 0:
            killed_types: Dict[UnitTypeId, int] = {}
            cutoff_time = self.bot.time - seconds_since_killed
            killed_units = Units([], self.bot)
            for i in range(len(self.enemies_killed)-1, -1, -1):
                enemy_unit, death_time = self.enemies_killed[i]
                killed_added = killed_types.get(enemy_unit.type_id, 0)
                if death_time >= cutoff_time:
                    if killed_added < 10:
                        killed_units.append(enemy_unit)
                        killed_types[enemy_unit.type_id] = killed_added + 1
                else:
                    break
            enemies += killed_units
        return enemies.filter(lambda unit: unit.type_id not in excluded_types)

    @timed
    def get_closest_target(self, friendly_unit: Unit, distance_limit=999999,
                           include_structures=True, include_units=True, include_destructables=False,
                           include_out_of_view=True, excluded_types=[], included_types=[], seconds_ahead: float=0) -> tuple[Unit | None, float]:
        nearest_enemy: Unit | None = None
        nearest_distance = distance_limit

        candidates: Units = self.get_candidates(include_structures, include_units, include_destructables,
                                                include_out_of_view, excluded_types, included_types)

        # ravens technically can't attack
        if friendly_unit.type_id != UnitTypeId.RAVEN:
            candidates = candidates.filter(lambda enemy: UnitTypes.can_attack_target(friendly_unit, enemy))
        for enemy in candidates:
            enemy_distance: float
            if seconds_ahead > 0:
                enemy_distance = friendly_unit.distance_to_squared(self.get_predicted_position(enemy, seconds_ahead))
            else:
                enemy_distance = self.distance_squared(friendly_unit, enemy, self.predicted_position)
            if (enemy_distance < nearest_distance):
                nearest_enemy = enemy
                nearest_distance = enemy_distance
        # can attack a destructable if no enemies in sight range
        if include_destructables and nearest_distance > 30:
            for destructable in self.bot.destructables:
                enemy_distance = friendly_unit.distance_to_squared(destructable)
                if (enemy_distance < nearest_distance):
                    nearest_enemy = destructable
                    nearest_distance = enemy_distance

        if nearest_enemy:
            nearest_distance = nearest_distance ** 0.5 - nearest_enemy.radius - friendly_unit.radius
        return (nearest_enemy, nearest_distance)

    @timed
    def get_closest_targets(self, friendly_unit: Unit, within_attack_buffer: float=0,
                           include_structures=True, include_units=True, include_destructables=False,
                           include_out_of_view=True, excluded_types=[], included_types=[]) -> Units:
        nearest_enemies: Units = Units([], self.bot)

        candidates: Units = self.get_candidates(include_structures, include_units, include_destructables,
                                                include_out_of_view, excluded_types, included_types)

        closest_enemy: Unit | None = None
        nearest_distance = float('inf')
        # ravens technically can't attack
        if friendly_unit.type_id != UnitTypeId.RAVEN:
            candidates = candidates.filter(lambda enemy: UnitTypes.can_attack_target(friendly_unit, enemy))
        for enemy in candidates:
            enemy_distance: float = self.distance_squared(friendly_unit, enemy, self.predicted_position)
            in_range_distance = self.get_attack_range_with_buffer_squared(friendly_unit, enemy, within_attack_buffer)
            if (enemy_distance < nearest_distance):
                closest_enemy = enemy
                nearest_distance = enemy_distance
            if enemy_distance <= in_range_distance:
                nearest_enemies.append(enemy)

        # return just the closest if none in range
        if nearest_enemies.amount == 0 and closest_enemy:
            nearest_enemies.append(closest_enemy)

        return nearest_enemies
    
    @timed
    def get_target_closer_than(self, friendly_unit: Unit, max_distance: float,
                               include_structures=True, include_units=True, include_destructables=False,
                               excluded_types=[], seconds_ahead: float=0) -> tuple[Unit | None, float]:
        candidates: Units = self.get_candidates(include_structures, include_units, include_destructables,
                                                excluded_types=excluded_types)
        for enemy in candidates:
            distance_limit = (max_distance + enemy.radius + friendly_unit.radius) ** 2
            enemy_distance: float
            if seconds_ahead > 0:
                enemy_distance = friendly_unit.distance_to_squared(self.get_predicted_position(enemy, seconds_ahead))
            else:
                enemy_distance = self.distance_squared(friendly_unit, enemy, self.predicted_position)
            if enemy_distance <= distance_limit:
                return (enemy, enemy_distance ** 0.5 - enemy.radius - friendly_unit.radius)
        return (None, 9999)

    @timed
    def get_enemies_in_range(self, friendly_unit: Unit, include_structures=True, include_units=True, include_destructables=False, excluded_types=[]) -> Units:
        enemies_in_range: Units = Units([], self.bot)
        candidates = self.get_candidates(include_structures, include_units, include_destructables, excluded_types=excluded_types)
        for candidate in candidates:
            range = self.distance(friendly_unit, candidate, self.predicted_position) - friendly_unit.radius - candidate.radius
            attack_range = UnitTypes.range_vs_target(friendly_unit, candidate)
            if range <= attack_range:
                enemies_in_range.append(candidate)
        return enemies_in_range

    @timed
    def get_candidates(self, include_structures=True, include_units=True, include_destructables=False,
                       include_out_of_view=True, excluded_types=[], included_types=[]):
        candidates: Units = Units([], self.bot)
        if include_structures and include_units:
            candidates = self.bot.enemy_units + self.bot.enemy_structures
        elif include_units:
            candidates = self.bot.enemy_units.copy()
        elif include_structures:
            candidates = self.bot.enemy_structures.copy()
        if include_out_of_view:
            candidates += self.recent_out_of_view(include_structures, include_units)
        if include_destructables:
            candidates += self.bot.destructables
        else:
            candidates += self.bot.destructables(UnitTypeId.COLLAPSIBLEROCKTOWERDEBRIS)
        if excluded_types:
            candidates = candidates.filter(lambda unit: unit.type_id not in excluded_types)
        if included_types:
            candidates = candidates.filter(lambda unit: unit.type_id in included_types)
        return candidates
    
    burrowing_unit_types = {
        UnitTypeId.LURKERMP,
        UnitTypeId.WIDOWMINE,
    }
    def enemies_needing_detection(self) -> Units:
        need_detection = self.enemies_in_view.filter(lambda unit: unit.is_cloaked or unit.is_burrowed or unit.type_id in self.burrowing_unit_types) + \
               self.enemies_out_of_view.filter(lambda unit: unit.is_cloaked or unit.is_burrowed or unit.type_id in self.burrowing_unit_types)
        creep_tumors_excluded = need_detection.filter(lambda unit: unit.type_id != UnitTypeId.CREEPTUMORBURROWED)
        if creep_tumors_excluded:
            return creep_tumors_excluded
        return need_detection

    out_of_view_cache: Dict[str, tuple[Units | None, float]] = {
        "all": (None, -1),
        "units": (None, -1),
        "structures": (None, -1),
    }
    @timed
    def recent_out_of_view(self, include_structures=True, include_units=True) -> Units:
        out_of_view, cache_time = self.out_of_view_cache["all"]
        if out_of_view is None or cache_time != self.bot.time:
            out_of_view = self.enemies_out_of_view.filter(
                lambda enemy_unit: self.bot.time - self.last_seen[enemy_unit.tag] < Enemy.unit_probably_moved_seconds)
            self.out_of_view_cache["all"] = (out_of_view, self.bot.time)
        if include_units and include_structures:
            return out_of_view
        elif include_units:
            out_of_view_units, cache_time = self.out_of_view_cache["units"]
            if out_of_view_units is None or cache_time != self.bot.time:
                out_of_view_units = out_of_view.filter(lambda enemy_unit: not enemy_unit.is_structure or enemy_unit.type_id == UnitTypeId.CREEPTUMOR)
                self.out_of_view_cache["units"] = (out_of_view_units, self.bot.time)
            return out_of_view_units
        else:
            # structures only
            out_of_view_structures, cache_time = self.out_of_view_cache["structures"]
            if out_of_view_structures is None or cache_time != self.bot.time:
                out_of_view_structures = out_of_view.filter(lambda enemy_unit: enemy_unit.is_structure)
                self.out_of_view_cache["structures"] = (out_of_view_structures, self.bot.time)
            return out_of_view_structures
    
    def get_total_count_of_type_seen(self, unit_type: UnitTypeId) -> int:
        return len(self.all_seen.get(unit_type, set()))

    @timed
    def detect_suddenly_seen_units(self, new_visible_enemies: Units):
        """Detect units that suddenly appear in vision range without being seen moving in."""
        prev_suddenly_seen_tags = self.suddenly_seen_units.tags
        self.suddenly_seen_units.clear()
        
        for enemy_unit in new_visible_enemies:
            if enemy_unit.tag in prev_suddenly_seen_tags:
                # continue tracking units already marked as suddenly seen
                self.suddenly_seen_units.append(enemy_unit)
                continue
            if enemy_unit.tag in self.enemies_in_view.tags:
                # already seen this unit before
                continue
            # Skip eggs, larvae, and structures (they don't "drop")
            if enemy_unit.type_id in (UnitTypeId.EGG, UnitTypeId.LARVA) or enemy_unit.is_structure:
                continue
            
            # Check if unit appeared well inside vision range (not at the edge)
            vision_buffer = 2.0  # Units appearing this far from vision edge are considered "suddenly seen"
            is_well_inside_vision = True
            
            # Check several points around the unit to see if they're all visible
            check_positions = [
                enemy_unit.position + Point2((0, vision_buffer)),
                enemy_unit.position + Point2((0, -vision_buffer)),
                enemy_unit.position + Point2((vision_buffer, 0)),
                enemy_unit.position + Point2((-vision_buffer, 0)),
            ]
            
            for pos in check_positions:
                if not self.bot.is_visible(pos):
                    break
            else:
                self.suddenly_seen_units.append(enemy_unit)
