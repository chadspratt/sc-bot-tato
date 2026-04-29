
from sc2.bot_ai import BotAI
from sc2.data import Race
from sc2.ids.unit_typeid import UnitTypeId
from sc2.unit import Unit

from bottato.enemy import Enemy
from bottato.enums import ArmyMode, BuildType, Tactic
from bottato.log_helper import LogHelper
from bottato.map.map import Map
from bottato.squad.enemy_intel import EnemyIntel
from bottato.unit_reference_helper import UnitReferenceHelper


class Tactics:
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, intel: EnemyIntel):
        self.bot = bot
        self.enemy = enemy
        self.map = map
        self.intel = intel
        self.army_mode = ArmyMode.STAGING

        self.last_values: dict[Tactic, bool] = {
            Tactic.BANSHEE_HARASS: False,
            Tactic.PROXY_BARRACKS: False,
            Tactic.RUSH_DEFENSE: False,
        }

        self.proxy_barracks: Unit | None = None

    def update_references(self):
        if self.proxy_barracks:
            try:
                self.proxy_barracks = UnitReferenceHelper.get_updated_unit_reference(self.proxy_barracks)
            except UnitReferenceHelper.UnitNotFound:
                self.proxy_barracks = None
        elif self.is_active(Tactic.PROXY_BARRACKS):
            # find the proxy barracks if we don't have a reference to it yet
            distant_barracks = self.bot.structures((UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING)).further_than(40, self.bot.start_location)
            if distant_barracks:
                self.proxy_barracks = distant_barracks[0]

    def is_active(self, tactic: Tactic) -> bool:
        new_value = False
        if tactic == Tactic.BANSHEE_HARASS:
            new_value = self.bot.time > 120 and self.bot.structures(UnitTypeId.STARPORT).ready.exists 
        elif tactic == Tactic.PROXY_BARRACKS:
            if BuildType.EARLY_EXPANSION in self.intel.enemy_builds_detected and self.intel.enemy_race != Race.Zerg:
                if self.intel.number_seen(UnitTypeId.BARRACKS) < 4 and not self._enemy_has_marine_counters():
                    if self.bot.time < 180:
                        # start the proxy
                        new_value = True
                    elif self.last_values[tactic] and self.proxy_barracks:
                        if self.bot.time < 240 and self.intel.army_ratio > 1.1 or self.intel.army_ratio > 3:
                            # keep it going if it's working
                            new_value = True
        elif tactic == Tactic.RUSH_DEFENSE:
            new_value = self.bot.time < 240 and BuildType.RUSH in self.intel.enemy_builds_detected
        if not new_value and self.last_values[tactic]:
            LogHelper.add_log(f"ending tactic {tactic}")

        self.last_values[tactic] = new_value
        return new_value

    # units that hard-counter early marines in small numbers
    MARINE_COUNTER_TYPES = {
        UnitTypeId.STALKER,
        UnitTypeId.MARAUDER, UnitTypeId.SIEGETANK, UnitTypeId.CYCLONE,
        UnitTypeId.ROACH, UnitTypeId.HYDRALISK,
    }

    def _enemy_has_marine_counters(self) -> bool:
        """Check if the enemy has units that hard-counter early marines."""
        enemy_army = self.enemy.get_army()
        return enemy_army.of_type(self.MARINE_COUNTER_TYPES).exists