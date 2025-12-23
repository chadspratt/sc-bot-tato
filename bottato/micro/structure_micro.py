from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.unit import Unit
from sc2.units import Units
from sc2.position import Point2

from bottato.unit_types import UnitTypes
from bottato.enemy import Enemy
from bottato.mixins import GeometryMixin, timed, timed_async
from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.micro.custom_effect import CustomEffect
from bottato.enums import RushType


class StructureMicro(BaseUnitMicro, GeometryMixin):
    def __init__(self, bot: BotAI, enemy: Enemy) -> None:
        self.bot: BotAI = bot
        self.enemy: Enemy = enemy
        self.command_center_destinations: dict[int, Point2 | None] = {}
        self.last_scan_time: float = 0

    @timed_async
    async def execute(self, rush_detected_types: set[RushType]):
        # logger.debug("adjust_supply_depots_for_enemies step")
        self.adjust_supply_depots_for_enemies(rush_detected_types)
        self.target_autoturrets()
        await self.move_command_centers()
        self.scan()

    @timed
    def adjust_supply_depots_for_enemies(self, rush_detected_types: set[RushType]):
        # Raise depos when enemies are nearby
        distance_threshold = 8 if rush_detected_types else 15
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOTLOWERED).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.is_flying:
                    continue
                if self.distance(enemy_unit, depot) < distance_threshold - 2:
                    depot(AbilityId.MORPH_SUPPLYDEPOT_RAISE)
                    # fake effect to tell units to get off the depot
                    BaseUnitMicro.custom_effects_to_avoid.append(CustomEffect(depot.position, depot.radius, self.bot.time, 1))
                    break
        # Lower depos when no enemies are nearby
        for depot in self.bot.structures(UnitTypeId.SUPPLYDEPOT).ready:
            for enemy_unit in self.bot.enemy_units:
                if enemy_unit.is_flying:
                    continue
                if self.distance(enemy_unit, depot) < distance_threshold:
                    break
            else:
                depot(AbilityId.MORPH_SUPPLYDEPOT_LOWER)

    @timed
    def target_autoturrets(self):
        turret: Unit
        for turret in self.bot.structures(UnitTypeId.AUTOTURRET):
            logger.debug(f"turret {turret} attacking")
            self._attack_something(turret, 0)

    @timed_async
    async def move_command_centers(self):
        for cc in self.bot.structures((UnitTypeId.COMMANDCENTER, UnitTypeId.COMMANDCENTERFLYING, UnitTypeId.ORBITALCOMMAND, UnitTypeId.ORBITALCOMMANDFLYING)).ready:
            if cc.is_flying:
                if cc.tag not in self.command_center_destinations:
                    self.command_center_destinations[cc.tag] = await self.bot.get_next_expansion()
                destination = self.command_center_destinations[cc.tag]
                if destination is None:
                    continue
                ccs_at_destination = self.bot.structures(UnitTypeId.COMMANDCENTER).closer_than(5, destination)
                if ccs_at_destination and cc.tag not in ccs_at_destination.tags:
                    # spot was taken, find a new one
                    self.command_center_destinations[cc.tag] = await self.bot.get_next_expansion()

                if self.bot.all_enemy_units:
                    nearby_enemies = self.bot.all_enemy_units.closer_than(15, cc)
                    if nearby_enemies:
                        threats = nearby_enemies.filter(lambda enemy: UnitTypes.can_attack_air(enemy))
                        if cc.health_percentage < 0.9:
                            bunker = self.bot.structures(UnitTypeId.BUNKER)
                            if bunker:
                                cc.move(bunker.first.position)
                            else:
                                cc.move(self.bot.main_base_ramp.top_center.towards(self.bot.start_location, 5)) # type: ignore
                        elif threats:
                            cc.move(self.bot.main_base_ramp.top_center)
                        else:
                            cc.move(destination)
                        continue
                if cc.position == destination:
                    BaseUnitMicro.add_custom_effect(cc.position, cc.radius, self.bot.time, 0.5)
                    cc(AbilityId.LAND, destination)
                else:
                    cc.move(destination)
            else:
                for expansion_location in self.bot.expansion_locations_list:
                    if cc.position.distance_to(expansion_location) < 5:
                        break
                else:
                    cc(AbilityId.LIFT)
                    return
                if cc.health_percentage < 0.8 and self.bot.enemy_units:
                    nearby_enemies = self.enemy.threats_to_friendly_unit(cc, attack_range_buffer=2)
                    if nearby_enemies:
                        threats = nearby_enemies.filter(lambda enemy: UnitTypes.can_attack_ground(enemy))
                        if threats:
                            self.command_center_destinations[cc.tag] = cc.position
                            cc(AbilityId.CANCEL_LAST)
                            cc(AbilityId.LIFT)

    @timed
    def scan(self):
        if self.bot.time - self.last_scan_time < 9:
            return
        orbital_with_energy = None
        for orbital in self.bot.structures(UnitTypeId.ORBITALCOMMAND).ready:
            if orbital.energy >= 50:
                orbital_with_energy = orbital
                break
        else:
            return
        need_detection = self.enemy.enemies_needing_detection()

        ravens = self.bot.units(UnitTypeId.RAVEN)
        enemies_to_scan = Units([], self.bot)
        air_attackers = None
        ground_attackers = None
        for enemy in need_detection:
            attackers = None
            # don't scan if raven nearby
            if self.closest_distance_squared(enemy, ravens) < 400:
                continue
            # only scan enemies if attackers nearby to make use of scan
            if enemy.is_flying:
                if air_attackers is None:
                    air_attackers = self.bot.units.filter(lambda u: UnitTypes.can_attack_air(u))
                attackers = air_attackers
            else:
                if ground_attackers is None:
                    ground_attackers = self.bot.units.filter(lambda u: UnitTypes.can_attack_ground(u))
                attackers = ground_attackers
            if not attackers:
                continue
            attackers = self.enemy.threats_to(enemy, attackers)
            if attackers.amount > 1:
                enemies_to_scan.append(enemy)

        # find unit that has most hidden enemies nearby then scan center of the group
        if enemies_to_scan:
            most_grouped_enemy, grouped_enemies = self.get_most_grouped_unit(enemies_to_scan, self.bot, 13)
            orbital_with_energy(AbilityId.SCANNERSWEEP_SCAN, grouped_enemies.center)
            self.last_scan_time = self.bot.time