from typing import List
from loguru import logger
from collections import deque

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from .mixins import UnitReferenceMixin, GeometryMixin
from .squad.enemy_squad import EnemySquad


class Enemy(UnitReferenceMixin, GeometryMixin):
    unit_probably_moved_seconds = 10
    unit_may_not_exist_seconds = 600
    enemy_squad_counter = 0
    frames_of_movement_history = 5

    def __init__(self, bot: BotAI):
        self.bot: BotAI = bot
        # probably need to refresh this
        self.enemies_in_view: Units = Units([], bot)
        self.enemies_out_of_view: Units = Units([], bot)
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
        self.bot.state.game_loop

    def update_references(self):
        for squad in self.enemy_squads:
            squad.update_references()
        # remove visible from out_of_view
        visible_tags = self.bot.enemy_units.tags.union(self.bot.enemy_structures.tags)
        logger.debug(f"visible tags: {visible_tags}")
        logger.debug(f"self.enemies_out_of_view: {self.enemies_out_of_view}")
        for enemy_unit in self.enemies_out_of_view:
            time_since_last_seen = self.bot.time - self.last_seen[enemy_unit.tag]
            if enemy_unit.tag in visible_tags or time_since_last_seen > self.unit_may_not_exist_seconds:
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
                        self.convert_point2_to_3(self.predicted_position[enemy_unit.tag]),
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

        # add not visible to out_of_view
        for enemy_unit in self.enemies_in_view:
            if enemy_unit.tag not in visible_tags:
                self.enemies_out_of_view.append(enemy_unit)
                self.predicted_position[enemy_unit.tag] = self.get_predicted_position(enemy_unit, 0)
        self.enemies_in_view = new_visible_enemies
        # self.update_squads()

    def get_predicted_position(self, unit: Unit, seconds_ahead: float) -> Point2:
        if unit.type_id in (UnitTypeId.COLLAPSIBLEROCKTOWERDEBRIS,):
            return unit.position
        time_since_last_seen = self.bot.time - self.last_seen[unit.tag]
        frame_vector = self.predicted_frame_vector[unit.tag]
        return self.predict_future_unit_position(unit, time_since_last_seen + seconds_ahead, frame_vector=frame_vector)

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
                break
        if not found:
            for enemy_unit in self.enemies_in_view:
                if enemy_unit.tag == unit_tag:
                    found = True
                    self.enemies_in_view.remove(enemy_unit)
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
                         if enemy_unit.target_in_range(friendly_unit, attack_range_buffer)],
                        self.bot)
        for enemy_unit in self.recent_out_of_view():
            if enemy_unit.can_attack_ground and not friendly_unit.is_flying:
                enemy_attack_range = enemy_unit.ground_range
            elif enemy_unit.can_attack_air and (friendly_unit.is_flying or friendly_unit.type_id == UnitTypeId.COLOSSUS):
                enemy_attack_range = enemy_unit.air_range
            else:
                continue
            if friendly_unit.distance_to(self.predicted_position[enemy_unit.tag]) < enemy_attack_range:
                threats.append(enemy_unit)
        return threats

    def threats_to_repairer(self, friendly_unit: Unit, attack_range_buffer=2) -> Units:
        threats = Units([enemy_unit for enemy_unit in self.enemies_in_view
                         if enemy_unit.target_in_range(friendly_unit, attack_range_buffer)],
                        self.bot)
        for enemy_unit in self.recent_out_of_view():
            enemy_attack_range = enemy_unit.ground_range
            if friendly_unit.distance_to(self.predicted_position[enemy_unit.tag]) < enemy_attack_range:
                threats.append(enemy_unit)
        return threats

    def get_enemies(self) -> Units:
        return self.enemies_in_view + self.recent_out_of_view()

    def get_army(self) -> Units:
        return (self.enemies_in_view + self.enemies_out_of_view).filter(lambda unit: not unit.is_structure and unit.type_id not in (UnitTypeId.SCV, UnitTypeId.MULE, UnitTypeId.DRONE, UnitTypeId.PROBE))

    def get_closest_target(self, friendly_unit: Unit, distance_limit=9999, include_structures=True, include_units=True, include_destructables=False, include_out_of_view=True, excluded_types=[], seconds_ahead=0) -> tuple[Unit, float]:
        nearest_enemy: Unit = None
        nearest_distance = distance_limit

        candidates: Units = self.get_candidates(include_structures, include_units, include_destructables, include_out_of_view, excluded_types)

        # ravens technically can't attack
        if friendly_unit.type_id != UnitTypeId.RAVEN:
            candidates = candidates.filter(lambda enemy: self.can_attack(friendly_unit, enemy))
        for enemy in candidates:
            enemy_distance = friendly_unit.distance_to(self.get_predicted_position(enemy, seconds_ahead)) - enemy.radius - friendly_unit.radius
            if (enemy_distance < nearest_distance):
                nearest_enemy = enemy
                nearest_distance = enemy_distance
        # can attack a destructable if no enemies in sight range
        if include_destructables and nearest_distance > 30:
            for destructable in self.bot.destructables:
                enemy_distance = friendly_unit.distance_to(destructable)
                if (enemy_distance < nearest_distance):
                    nearest_enemy = destructable
                    nearest_distance = enemy_distance

        return (nearest_enemy, nearest_distance)

    def get_enemies_in_range(self, friendly_unit: Unit, include_structures=True, include_units=True, include_destructables=False, excluded_types=[]) -> Units:
        enemies_in_range: Units = Units([], self.bot)
        candidates = self.get_candidates(include_structures, include_units, include_destructables, excluded_types)
        for candidate in candidates:
            range = self.distance(friendly_unit, candidate)
            if candidate.is_flying:
                if range < friendly_unit.air_range:
                    enemies_in_range.append(candidate)
            elif range < friendly_unit.ground_range or candidate.type_id == UnitTypeId.COLOSSUS and range < friendly_unit.air_range:
                enemies_in_range.append(candidate)
        return enemies_in_range

    def get_candidates(self, include_structures=True, include_units=True, include_destructables=False, include_out_of_view=True, excluded_types=[]):
        candidates: Units = None
        if include_structures and include_units:
            candidates = self.bot.enemy_units + self.bot.enemy_structures
            if include_out_of_view:
                candidates += self.recent_out_of_view()
        elif include_units:
            candidates = self.bot.enemy_units + []
            if include_out_of_view:
                candidates += self.recent_out_of_view().filter(lambda unit: not unit.is_structure or unit.type_id == UnitTypeId.CREEPTUMOR)
        elif include_structures:
            candidates = self.bot.enemy_structures + []
            if include_out_of_view:
                candidates += self.recent_out_of_view().filter(lambda unit: unit.is_structure)
        if include_destructables:
            candidates += self.bot.destructables
        else:
            candidates += self.bot.destructables(UnitTypeId.COLLAPSIBLEROCKTOWERDEBRIS)
        if excluded_types:
            candidates = candidates.filter(lambda unit: unit.type_id not in excluded_types)
        return candidates

    def recent_out_of_view(self) -> Units:
        return self.enemies_out_of_view.filter(
            lambda enemy_unit: self.bot.time - self.last_seen[enemy_unit.tag] < Enemy.unit_probably_moved_seconds)

    def can_attack(self, friendly: Unit, enemy: Unit) -> bool:
        return friendly.can_attack_ground and not enemy.is_flying or friendly.can_attack_air and (enemy.is_flying or enemy.type_id == UnitTypeId.COLOSSUS)
