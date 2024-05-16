from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from .mixins import UnitReferenceMixin, GeometryMixin
from .enemy_squad import EnemySquad


class Enemy(UnitReferenceMixin, GeometryMixin):
    unit_probably_moved_seconds = 5

    def __init__(self, bot: BotAI):
        self.bot: BotAI = bot
        # probably need to refresh this
        self.enemies_in_view: Units = []
        self.enemies_out_of_view: Units = []
        self.last_seen: dict[int, float] = {}
        self.last_seen_position: dict[int, Point2] = {}
        self.predicted_position: dict[int, Point2] = {}
        self.enemy_squads: list[EnemySquad] = []
        self.squads_by_unit_tag: dict[int, EnemySquad] = {}

    def update_references(self):
        for squad in self.enemy_squads:
            squad.update_references()
        # remove visible from out_of_view
        for enemy_unit in self.enemies_out_of_view:
            if enemy_unit.tag in self.bot.enemy_units.tags:
                self.enemies_out_of_view.remove(enemy_unit)
            else:
                # assume unit continues in same direction
                self.predicted_position[enemy_unit.tag] = self.predict_future_unit_position(
                    enemy_unit, self.bot.time - self.last_seen[enemy_unit.tag])
                
                if self.bot.time - self.last_seen[enemy_unit.tag] <= Enemy.unit_probably_moved_seconds:
                    self.bot.client.debug_box2_out(
                        self.convert_point2_to_3(self.predicted_position[enemy_unit.tag]),
                        half_vertex_length=enemy_unit.radius,
                        color=(255, 0, 0)
                    )
            # TODO check if position is visible
            # TODO guess updated position based on last facing
            # TODO something with last_seen
        # set last_seen for visible
        for enemy_unit in self.bot.enemy_units:
            self.last_seen[enemy_unit.tag] = self.bot.time
            self.last_seen_position[enemy_unit.tag] = enemy_unit.position
        # add not visible to out_of_view
        for enemy_unit in self.enemies_in_view:
            if enemy_unit.tag not in self.bot.enemy_units.tags:
                self.enemies_out_of_view.append(enemy_unit)
                self.predicted_position[enemy_unit.tag] = enemy_unit.position
        self.enemies_in_view = self.bot.enemy_units

    def threats_to(self, friendly_unit: Unit, attack_range_buffer=2) -> list[Unit]:
        threats = [enemy_unit for enemy_unit in self.enemies_in_view
                   if enemy_unit.target_in_range(friendly_unit, attack_range_buffer)]
        for enemy_unit in self.enemies_out_of_view:
            if self.bot.time - self.last_seen[enemy_unit.tag] > Enemy.unit_probably_moved_seconds:
                continue
            if enemy_unit.can_attack_ground and not friendly_unit.is_flying:
                enemy_attack_range = enemy_unit.ground_range
            elif enemy_unit.can_attack_air and (friendly_unit.is_flying or friendly_unit.type_id == UnitTypeId.COLOSSUS):
                enemy_attack_range = enemy_unit.air_range
            else:
                continue
            if friendly_unit.distance_to(self.predicted_position[enemy_unit.tag]) < enemy_attack_range:
                threats.append(enemy_unit)
        return threats

    def find_nearby_squad(self, enemy_unit: Unit) -> EnemySquad:
        for enemy_squad in self.enemy_squads:
            if enemy_squad.near(enemy_unit):
                return enemy_squad
        return EnemySquad(self.bot)

    def update_squads(self):
        for enemy_unit in self.enemies_in_view:
            if enemy_unit.tag not in self.squads_by_unit_tag.keys():
                nearby_squad: EnemySquad = self.find_nearby_squad(enemy_unit)
                nearby_squad.recruit(enemy_unit)
                self.squads_by_unit_tag[enemy_unit.tag] = nearby_squad
            else:
                current_squad = self.squads_by_unit_tag[enemy_unit.tag]
                if not current_squad.near(enemy_unit):
                    # reassign
                    nearby_squad: EnemySquad = self.find_nearby_squad(enemy_unit)
                    nearby_squad.transfer(enemy_unit)
                    self.squads_by_unit_tag[enemy_unit.tag] = nearby_squad
