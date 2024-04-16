import math
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from .scouting import Scouting
from .squad import Squad
from .enemy import Enemy

from .mixins import VectorFacingMixin


class Military(VectorFacingMixin):
    def __init__(self, bot: BotAI, enemy: Enemy) -> None:
        self.bot: BotAI = bot
        self.enemy = enemy
        self.unassigned_army = Squad(
            bot=bot,
        )
        self.scouting = Scouting(self.bot, enemy)
        self.new_damage_taken: dict[int, float] = {}
        self.squads = [
            # Squad(
            #     bot=bot,
            #     composition={UnitTypeId.REAPER: 2},
            #     color=(0, 0, 255),
            #     name="alpha",
            # ),
            Squad(
                bot=bot,
                composition={UnitTypeId.HELLION: 2, UnitTypeId.REAPER: 1},
                color=(255, 255, 0),
                name="burninate",
            ),
            Squad(
                bot=bot,
                composition={
                    UnitTypeId.CYCLONE: 1,
                    UnitTypeId.MARINE: 4,
                    UnitTypeId.RAVEN: 1,
                },
                color=(255, 0, 255),
                name="seek",
            ),
            Squad(
                bot=bot,
                composition={
                    UnitTypeId.SIEGETANK: 1,
                    UnitTypeId.MARINE: 4,
                    UnitTypeId.RAVEN: 1,
                },
                color=(255, 0, 0),
                name="destroy",
            ),
            Squad(
                bot=bot,
                composition={
                    UnitTypeId.SIEGETANK: 1,
                    UnitTypeId.MARINE: 2,
                    UnitTypeId.RAVEN: 1,
                },
                color=(0, 255, 255),
                name="defend",
            ),
        ]

    def report_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.tag not in self.new_damage_taken:
            self.new_damage_taken[unit.tag] = amount_damage_taken
        else:
            self.new_damage_taken[unit.tag] += amount_damage_taken

    def muster_workers(self, position: Point2, count: int = 5):
        pass

    def report(self):
        _report = "Military: "
        for squad in self.squads:
            _report += squad.get_report() + ", "
        _report += self.unassigned_army.get_report()
        logger.info(_report)

    def update_references(self):
        self.unassigned_army.update_references()
        for squad in self.squads:
            squad.update_references()

    def manage_squads(self):
        self.unassigned_army.draw_debug_box()
        for unassigned in self.unassigned_army.units:
            if self.scouting.scouts_needed > 0:
                self.unassigned_army.transfer(unassigned, self.scouting)
                continue
            for squad in self.squads:
                if squad.needs(unassigned):
                    self.unassigned_army.transfer(unassigned, squad)
                    break

        self.scouting.update_visibility()
        self.scouting.move_scouts(self.new_damage_taken)

        for i, squad in enumerate(self.squads):
            if not squad.units:
                continue
            squad.draw_debug_box()
            squad.update_formation()
            if self.enemy.enemies_in_view:
                logger.debug(f"squad {squad.name} is full")
                squad.attack(self.enemy.enemies_in_view)
            elif not squad.is_full:
                map_center = self.bot.game_info.map_center
                staging_location = self.bot.start_location.towards(
                    map_center, distance=10 + i * 5
                )
                # facing = self.get_facing(squad.position, staging_location) if squad.position else squad.slowest_unit.facing
                squad.move(staging_location, math.pi * 3 / 2)
                # squad.move(staging_location, self.get_facing(self.bot.start_location, staging_location))
            elif self.bot.enemy_structures:
                logger.debug(f"squad {squad.name} is full")
                squad.attack(self.bot.enemy_structures)
            else:
                squad.move(squad._destination, squad.destination_facing)

        self.report()
        self.new_damage_taken.clear()
