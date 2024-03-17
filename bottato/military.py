from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from .squad import Squad


class Formation:
    def __init__(self, position: Point2, front: Point2, units: list[Unit] = []):
        self.units = units
        self.position = position
        self.front = front


class Military:
    def __init__(self, bot: BotAI) -> None:
        self.bot: BotAI = bot
        self.unassigned_army = Squad(
            bot,
        )
        self.squads = [
            Squad(
                bot, composition={UnitTypeId.REAPER: 2}, color=(0, 0, 255), name="alpha"
            ),
            Squad(
                bot,
                composition={UnitTypeId.HELLION: 2, UnitTypeId.REAPER: 1},
                color=(255, 255, 0),
                name="burninate",
            ),
            Squad(
                bot,
                composition={
                    UnitTypeId.CYCLONE: 1,
                    UnitTypeId.MARINE: 4,
                    UnitTypeId.RAVEN: 1,
                },
                color=(255, 0, 255),
                name="seek",
            ),
            Squad(
                bot,
                composition={
                    UnitTypeId.SIEGETANK: 1,
                    UnitTypeId.MARINE: 4,
                    UnitTypeId.RAVEN: 1,
                },
                color=(255, 0, 0),
                name="destroy",
            ),
            Squad(
                bot,
                composition={
                    UnitTypeId.SIEGETANK: 1,
                    UnitTypeId.MARINE: 2,
                    UnitTypeId.RAVEN: 1,
                },
                color=(0, 255, 255),
                name="defend",
            ),
        ]

    def muster_workers(self, position: Point2, count: int = 5):
        pass

    def manage_squads(self, enemies_in_view: list[Unit]):
        self.unassigned_army.manage_paperwork()
        self.unassigned_army.draw_debug_box()
        for unassigned in self.unassigned_army.units:
            for squad in self.squads:
                if squad.needs(unassigned):
                    self.unassigned_army.transfer(unassigned, squad)
                    break
        for squad in self.squads:
            squad.manage_paperwork()
            squad.draw_debug_box()
            if squad.is_full:
                logger.info(f"squad {squad.name} is full")
                map_center = self.bot.game_info.map_center
                staging_location = self.bot.start_location.towards(
                    map_center, distance=10
                )
                squad.move(staging_location)
        for squad in self.squads:
            if squad.is_full:
                squad.attack(enemies_in_view, is_priority=True)
        # if not alpha_squad.has_orders and self.enemies_in_view:
        #     alpha_squad.attack(self.enemies_in_view[0])

    def manage_formations(self):
        # create formation if there are none
        if not self.formations:
            self
        # gather unassigned units to formations
