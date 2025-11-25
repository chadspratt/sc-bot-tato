from typing import Dict, List
from loguru import logger
from collections import deque

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bottato.unit_types import UnitTypes
from bottato.mixins import UnitReferenceMixin, GeometryMixin, TimerMixin
from bottato.squad.enemy_squad import EnemySquad


class Enemy(UnitReferenceMixin, GeometryMixin, TimerMixin):
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
        self.first_seen: dict[int, float] = {}
        self.last_seen: dict[int, float] = {}
        self.last_seen_step: dict[int, int] = {}
        self.last_seen_position: dict[int, Point2] = {}
        self.last_seen_positions: dict[int, deque] = {}
        self.predicted_position: dict[int, Point2] = {}
        self.predicted_frame_vector: dict[int, Point2] = {}
        self.enemy_squads: List[EnemySquad] = []
        self.squads_by_unit_tag: dict[int, EnemySquad] = {}
        self.all_seen: dict[UnitTypeId, set[int]] = {}

    def update_references(self, units_by_tag: dict[int, Unit]):
        self.start_timer("enemy.update_references")
        for squad in self.enemy_squads:
            squad.update_references(units_by_tag)
        # remove visible from out_of_view
        visible_tags = self.bot.enemy_units.tags.union(self.bot.enemy_structures.tags)
        logger.debug(f"visible tags: {visible_tags}")
        logger.debug(f"self.enemies_out_of_view: {self.enemies_out_of_view}")
        for enemy_unit in self.enemies_out_of_view:
            time_since_last_seen = self.bot.time - self.last_seen[enemy_unit.tag]
            if enemy_unit.is_structure and self.bot.is_visible(enemy_unit.position):
                self.enemies_out_of_view.remove(enemy_unit)
            elif enemy_unit.tag in visible_tags or time_since_last_seen > self.unit_may_not_exist_seconds:
                self.enemies_out_of_view.remove(enemy_unit)
            else:
                # assume unit continues in same direction
                new_prediction = self.get_predicted_position(enemy_unit, 0)
                # back the projection up to edge of visibility we can see that it isn't there
                reverse_vector = None
                while self.bot.is_visible(new_prediction):
                    if self.last_seen_position[enemy_unit.tag] == new_prediction:
                        # seems to be some fuzziness where building pos is visible but building is not in enemy_structures
                        break
                    logger.debug(f"enemy not where predicted {enemy_unit}")
                    if reverse_vector is None:
                        reverse_vector = (self.last_seen_position[enemy_unit.tag] - new_prediction).normalized
                    new_prediction += reverse_vector
                self.predicted_position[enemy_unit.tag] = new_prediction

                if time_since_last_seen <= self.unit_probably_moved_seconds:
                    self.bot.client.debug_box2_out(
                        self.convert_point2_to_3(self.predicted_position[enemy_unit.tag], self.bot),
                        half_vertex_length=enemy_unit.radius,
                        color=(255, 0, 0)
                    )

        # set last_seen for visible
        new_visible_enemies: Units = self.bot.enemy_units + self.bot.enemy_structures
        for enemy_unit in new_visible_enemies:
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

        # add not visible to out_of_view
        for enemy_unit in self.enemies_in_view:
            if enemy_unit.tag not in visible_tags:
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
        self.enemies_in_view = new_visible_enemies
        # self.update_squads()
        self.stop_timer("enemy.update_references")

    def get_predicted_position(self, unit: Unit, seconds_ahead: float) -> Point2:
        if unit.type_id in (UnitTypeId.COLLAPSIBLEROCKTOWERDEBRIS,):
            return unit.position
        if unit.age > 0 and unit not in self.enemies_out_of_view:
            return unit.position
        time_since_last_seen = self.bot.time - self.last_seen[unit.tag]
        frame_vector = self.predicted_frame_vector[unit.tag]
        return self.predict_future_unit_position(unit, time_since_last_seen + seconds_ahead, self.bot, frame_vector=frame_vector)

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
        while i < sample_count:
            end: Point2 = recent_positions[i]
            sum += end - start
            i += 1
        sum /= sample_count - 1
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
            # enemy_squad = self.squads_by_unit_tag[unit_tag]
            # enemy_squad.remove_by_tag(unit_tag)
            # del self.squads_by_unit_tag[unit_tag]
            # if enemy_squad.is_empty:
            #     self.enemy_squads.remove(enemy_squad)

    def _find_nearby_squad(self, enemy_unit: Unit) -> EnemySquad:
        for enemy_squad in self.enemy_squads:
            if enemy_squad.near(enemy_unit, self.predicted_position):
                return enemy_squad
        new_squad = EnemySquad(bot=self.bot, number=self.enemy_squad_counter)
        self.enemy_squad_counter += 1
        self.enemy_squads.append(new_squad)
        return new_squad

    def update_squads(self):
        for enemy_unit in self.enemies_in_view:
            if enemy_unit.tag not in self.squads_by_unit_tag.keys():
                nearby_squad: EnemySquad = self._find_nearby_squad(enemy_unit)
                nearby_squad.recruit(enemy_unit)
                self.squads_by_unit_tag[enemy_unit.tag] = nearby_squad
            else:
                current_squad = self.squads_by_unit_tag[enemy_unit.tag]
                if not current_squad.near(enemy_unit, self.predicted_position):
                    # reassign
                    nearby_squad: EnemySquad = self._find_nearby_squad(enemy_unit)
                    current_squad.transfer(enemy_unit, nearby_squad)
                    self.squads_by_unit_tag[enemy_unit.tag] = nearby_squad

    def threats_to(self, friendly_unit: Unit, attack_range_buffer=2) -> Units:
        threats = Units([enemy_unit for enemy_unit in self.enemies_in_view
                         if UnitTypes.target_in_range(enemy_unit, friendly_unit, attack_range_buffer)],
                        self.bot)
        range_limits: Dict[UnitTypeId, float] = {}
        for enemy_unit in self.recent_out_of_view():
            if enemy_unit.type_id not in range_limits:
                enemy_attack_range = UnitTypes.range_vs_target(enemy_unit, friendly_unit)
                if enemy_attack_range == 0.0:
                    range_limits[enemy_unit.type_id] = 0
                else:
                    range_limits[enemy_unit.type_id] = (enemy_attack_range + attack_range_buffer) ** 2
            range_limit = range_limits[enemy_unit.type_id]
            if range_limit == 0:
                continue
            if friendly_unit.distance_to_squared(self.predicted_position[enemy_unit.tag]) <= range_limit:
                threats.append(enemy_unit)
        return threats

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
            if friendly_unit.distance_to_squared(self.predicted_position[enemy_unit.tag]) < range_limit:
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
            killed_types: dict[UnitTypeId, int] = {}
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
        return enemies.filter(lambda unit: not unit.is_structure and unit.type_id not in excluded_types)

    def get_closest_target(self, friendly_unit: Unit, distance_limit=999999,
                           include_structures=True, include_units=True, include_destructables=False,
                           include_out_of_view=True, excluded_types=[], seconds_ahead: float=0) -> tuple[Unit | None, float]:
        nearest_enemy: Unit | None = None
        nearest_distance = distance_limit

        candidates: Units = self.get_candidates(include_structures, include_units, include_destructables,
                                                include_out_of_view, excluded_types)

        # ravens technically can't attack
        if friendly_unit.type_id != UnitTypeId.RAVEN:
            candidates = candidates.filter(lambda enemy: UnitTypes.can_attack_target(friendly_unit, enemy))
        for enemy in candidates:
            enemy_distance: float
            if seconds_ahead > 0:
                enemy_distance = friendly_unit.distance_to_squared(self.get_predicted_position(enemy, seconds_ahead))
            else:
                enemy_distance = self.distance_squared(friendly_unit, enemy)
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
    
    def get_target_closer_than(self, friendly_unit: Unit, max_distance: float,
                               include_structures=True, include_units=True, include_destructables=False,
                               excluded_types=[], seconds_ahead: float=0) -> tuple[Unit | None, float]:
        candidates: Units = self.get_candidates(include_structures, include_units, include_destructables,
                                                True, excluded_types)
        distance_limit = max_distance ** 2
        for enemy in candidates:
            enemy_distance: float
            if seconds_ahead > 0:
                enemy_distance = friendly_unit.distance_to_squared(self.get_predicted_position(enemy, seconds_ahead))
            else:
                enemy_distance = self.distance_squared(friendly_unit, enemy)
            if enemy_distance < distance_limit:
                return (enemy, enemy_distance ** 0.5 - enemy.radius - friendly_unit.radius)
        return (None, 9999)

    def get_enemies_in_range(self, friendly_unit: Unit, include_structures=True, include_units=True, include_destructables=False, excluded_types=[]) -> Units:
        enemies_in_range: Units = Units([], self.bot)
        candidates = self.get_candidates(include_structures, include_units, include_destructables, excluded_types)
        for candidate in candidates:
            range = self.distance(friendly_unit, candidate) - friendly_unit.radius - candidate.radius
            attack_range = UnitTypes.range_vs_target(friendly_unit, candidate)
            if range <= attack_range:
                enemies_in_range.append(candidate)
        return enemies_in_range

    def get_candidates(self, include_structures=True, include_units=True, include_destructables=False,
                       include_out_of_view=True, excluded_types=[]):
        candidates: Units = Units([], self.bot)
        if include_structures and include_units:
            candidates = self.bot.enemy_units + self.bot.enemy_structures
            if include_out_of_view:
                candidates += self.recent_out_of_view()
        elif include_units:
            candidates = self.bot.enemy_units.copy()
            if include_out_of_view:
                candidates += self.recent_out_of_view().filter(lambda unit: not unit.is_structure or unit.type_id == UnitTypeId.CREEPTUMOR)
        elif include_structures:
            candidates = self.bot.enemy_structures.copy()
            if include_out_of_view:
                candidates += self.recent_out_of_view().filter(lambda unit: unit.is_structure)
        if include_destructables:
            candidates += self.bot.destructables
        else:
            candidates += self.bot.destructables(UnitTypeId.COLLAPSIBLEROCKTOWERDEBRIS)
        if excluded_types:
            candidates = candidates.filter(lambda unit: unit.type_id not in excluded_types)
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

    def recent_out_of_view(self) -> Units:
        return self.enemies_out_of_view.filter(
            lambda enemy_unit: self.bot.time - self.last_seen[enemy_unit.tag] < Enemy.unit_probably_moved_seconds)
    
    def get_total_count_of_type_seen(self, unit_type: UnitTypeId) -> int:
        return len(self.all_seen.get(unit_type, set()))
