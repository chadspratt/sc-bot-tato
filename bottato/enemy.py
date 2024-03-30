from typing import List, Dict

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units

from .mixins import UnitReferenceMixin
from .enemy_squad import EnemySquad


class Enemy(UnitReferenceMixin):
    def __init__(self, bot: BotAI):
        self.bot: BotAI = bot
        # probably need to refresh this
        self.enemies_in_view: Units = []
        self.enemy_squads: list[EnemySquad] = []
        self.squads_by_unit_tag = Dict[int, EnemySquad]

    def update_references(self):
        for squad in self.enemy_squads:
            squad.update_unit_references()

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
