from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.position import Point2

from bottato.enemy import Enemy
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin, TimerMixin


class StructureMicro(BaseUnitMicro, GeometryMixin, TimerMixin):
    def __init__(self, bot: BotAI, enemy: Enemy) -> None:
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.formations = []
        self.command_center_destinations: dict[int, Point2] = {}

    async def execute(self, rush_detected: bool):
        self.start_timer("structure_micro.execute")
        # logger.debug("adjust_supply_depots_for_enemies step")
        self.adjust_supply_depots_for_enemies(rush_detected)
        self.target_autoturrets()
        await self.move_command_centers()
        self.stop_timer("structure_micro.execute")

    def adjust_supply_depots_for_enemies(self, rush_detected: bool):
        # Raise depos when enemies are nearby
        distance_threshold = 15 if rush_detected else 8
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for enemy_unit in self.bot.enemy_units:
                if self.distance(enemy_unit, depot) < distance_threshold - 2:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    break
        # Lower depos when no enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for enemy_unit in self.bot.enemy_units:
                if self.distance(enemy_unit, depot) < 8:
                    break
            else:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    def target_autoturrets(self):
        turret: Unit
        for turret in self.bot.structures(UnitTypeId.AUTOTURRET):
            logger.debug(f"turret {turret} attacking")
            self.attack_something(turret, 0)

    async def move_command_centers(self):
        for cc in self.bot.structures((UnitTypeId.COMMANDCENTER, UnitTypeId.COMMANDCENTERFLYING, UnitTypeId.ORBITALCOMMAND, UnitTypeId.ORBITALCOMMANDFLYING)).ready:
            if cc.is_flying:
                if cc.tag not in self.command_center_destinations:
                    self.command_center_destinations[cc.tag] = await self.bot.get_next_expansion()
                destination = self.command_center_destinations[cc.tag]
                if self.bot.enemy_units:
                    nearby_enemies = self.bot.enemy_units.closer_than(15, cc)
                    if nearby_enemies:
                        threats = nearby_enemies.filter(lambda enemy: enemy.can_attack_air)
                        if threats:
                            cc.move(self.bot.main_base_ramp.top_center)
                        else:
                            cc.move(destination)
                        continue
                if cc.position == destination:
                    cc(AbilityId.LAND, destination)
                else:
                    cc.move(destination)
            else:
                for expansion_location in self.bot.expansion_locations_list:
                    if cc.position.distance_to(expansion_location) < 5:
                        break
                else:
                    cc(AbilityId.LIFT)
                if cc.health_percentage < 0.5 and self.bot.enemy_units:
                    nearby_enemies = self.bot.enemy_units.closer_than(6, cc)
                    if nearby_enemies:
                        threats = nearby_enemies.filter(lambda enemy: enemy.can_attack_ground)
                        if threats:
                            self.command_center_destinations[cc.tag] = cc.position
                            # XXX need to cancel whatever it's doing to be able to lift
                            cc(AbilityId.LIFT)
