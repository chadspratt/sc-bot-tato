
from typing import Dict

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
    def __init__(self, bot: BotAI):
        self.bot = bot
        
        self.enemy: Enemy = Enemy(bot)
        self.map = Map(bot)
        self.intel = EnemyIntel(bot, self.map, self.enemy)

        self.army_mode = ArmyMode.STAGING

        self.last_values: Dict[Tactic, bool] = {
            Tactic.BANSHEE_HARASS: False,
            Tactic.PROXY_BARRACKS: False,
            Tactic.RUSH_DEFENSE: False,
            Tactic.MEDIVAC_HARASS: False,
            Tactic.RAMP_SECURED: False,
            Tactic.WORKER_RUSH_DEFENCE: False,
            Tactic.WORKER_RUSH_COUNTER_ATTACK: False,
            Tactic.WALL_IS_BUILT: False,
        }
        self.last_updates: Dict[Tactic, int] = {
                Tactic.BANSHEE_HARASS: 0,
                Tactic.PROXY_BARRACKS: 0,
                Tactic.RUSH_DEFENSE: 0,
                Tactic.MEDIVAC_HARASS: 0,
                Tactic.RAMP_SECURED: 0,
                Tactic.WORKER_RUSH_DEFENCE: 0,
                Tactic.WORKER_RUSH_COUNTER_ATTACK: 0,
                Tactic.WALL_IS_BUILT: 0,
        }

        self.proxy_barracks: Unit | None = None

    def update_references(self):
        if self.proxy_barracks:
            try:
                self.proxy_barracks = UnitReferenceHelper.get_updated_unit(self.proxy_barracks)
            except UnitReferenceHelper.UnitNotFound:
                self.proxy_barracks = None
        elif self.is_active(Tactic.PROXY_BARRACKS):
            # find the proxy barracks if we don't have a reference to it yet
            distant_barracks = self.bot.structures((UnitTypeId.BARRACKS, UnitTypeId.BARRACKSFLYING)).further_than(40, self.bot.start_location)
            if distant_barracks:
                self.proxy_barracks = distant_barracks[0]

    def set_active(self, tactic: Tactic, value: bool):
        if value and not self.last_values[tactic]:
            LogHelper.add_log(f"starting tactic {tactic}")
        self.last_values[tactic] = value

    def is_active(self, tactic: Tactic) -> bool:
        new_value = False

        if self.last_updates[tactic] == self.bot.state.game_loop:
            new_value = self.last_values[tactic]
        elif tactic == Tactic.BANSHEE_HARASS:
            new_value = self.bot.time > 120 and self.bot.structures(UnitTypeId.STARPORT).ready.exists 
        elif tactic == Tactic.PROXY_BARRACKS:
            if BuildType.EARLY_EXPANSION in self.intel.enemy_builds_detected and self.intel.enemy_race != Race.Zerg:
                if self.intel.number_seen(UnitTypeId.BARRACKS) < 4 and not self._enemy_has_marine_counters():
                    if self.bot.time < 180:
                        # start the proxy
                        new_value = True
                    elif self.last_values[tactic] and self.proxy_barracks:
                        # keep it going if it's working
                        new_value = self.bot.enemy_units([UnitTypeId.HELLION]).amount == 0 \
                            and (self.bot.time < 240 and self.intel.army_ratio > 1.1
                                 or self.intel.army_ratio > 3)
        elif tactic == Tactic.RUSH_DEFENSE:
            new_value = (
                self.bot.time < 240
                and BuildType.RUSH in self.intel.enemy_builds_detected
                and BuildType.CANNON_RUSH not in self.intel.enemy_builds_detected
            )
        elif tactic == Tactic.WORKER_RUSH_DEFENCE:
            new_value = (
                BuildType.WORKER_RUSH in self.intel.enemy_builds_detected
                and (self.bot.time < 150 or self.bot.units.exclude_type(UnitTypeId.SCV).amount < 3)
            )
        elif tactic == Tactic.WORKER_RUSH_COUNTER_ATTACK:
            new_value = (
                BuildType.WORKER_RUSH in self.intel.enemy_builds_detected
                and not self.is_active(Tactic.WORKER_RUSH_DEFENCE)
                and self.bot.time > 100
            )
        elif tactic == Tactic.WALL_IS_BUILT:
            new_value = (
                self.bot.structures(
                    (UnitTypeId.SUPPLYDEPOT, UnitTypeId.SUPPLYDEPOTLOWERED, UnitTypeId.BARRACKS)
                ).closer_than(
                    4, self.bot.main_base_ramp.top_center
                ).amount >= 3
            )
        else:
            new_value = self.last_values[tactic]

        if not new_value and self.last_values[tactic]:
            LogHelper.add_log(f"ending tactic {tactic}")

        self.last_values[tactic] = new_value
        self.last_updates[tactic] = self.bot.state.game_loop

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