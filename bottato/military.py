import math
from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from .squad.squad_type import SquadType, SquadTypeDefinitions
from .squad.base_squad import BaseSquad
from .squad.scouting import Scouting
from .squad.formation_squad import FormationSquad
from .enemy import Enemy
from .map import Map

from .mixins import GeometryMixin, DebugMixin


class Military(GeometryMixin, DebugMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map) -> None:
        self.bot: BotAI = bot
        self.enemy = enemy
        self.map = map
        self.main_army = FormationSquad(
            bot=bot,
            enemy=enemy,
            map=map,
            type=SquadTypeDefinitions['none'],
            color=self.random_color(),
            name='main'
        )
        self.scouting = Scouting(self.bot, enemy, self.random_color())
        self.new_damage_taken: dict[int, float] = {}
        self.squads_by_unit_tag: dict[int, BaseSquad] = {}
        self.squads: List[BaseSquad] = []
        self.squads.append(self.main_army)
        self.created_squad_type_counts: dict[int, int] = {}
        self.offense_start_supply = 200

    def add_to_main(self, unit: Unit) -> None:
        self.main_army.recruit(unit)
        self.squads_by_unit_tag[unit.tag] = self.main_army

    def add_squad(self, squad_type: SquadType) -> FormationSquad:
        new_squad = FormationSquad(bot=self.bot,
                                   type=squad_type,
                                   enemy=self.enemy,
                                   map=self.map,
                                   color=self.random_color(),
                                   name=self.create_squad_name(squad_type))
        self.squads.append(new_squad)
        logger.info(f"add squad {new_squad} of type {squad_type}")
        return new_squad

    def create_squad_name(self, squad_type: SquadType) -> str:
        if squad_type.name in self.created_squad_type_counts:
            next_value = self.created_squad_type_counts[squad_type.name] + 1
        else:
            next_value = 1
        self.created_squad_type_counts[squad_type.name] = next_value
        return f'{squad_type.name}_{next_value}'

    def report_damage(self, unit: Unit, amount_damage_taken: float):
        if unit.tag not in self.new_damage_taken:
            self.new_damage_taken[unit.tag] = amount_damage_taken
        else:
            self.new_damage_taken[unit.tag] += amount_damage_taken

    def muster_workers(self, position: Point2, count: int = 5):
        pass

    async def manage_squads(self, iteration: int):
        self.main_army.draw_debug_box()
        while self.scouting.scouts_needed:
            logger.debug(f"scouts needed: {self.scouting.scouts_needed}")
            for unit in self.main_army.units:
                if self.scouting.needs(unit):
                    logger.info(f"adding {unit} to scouts")
                    self.main_army.transfer(unit, self.scouting)
                    self.squads_by_unit_tag[unit.tag] = self.scouting
                    break
            else:
                break

        self.scouting.update_visibility()
        await self.scouting.move_scouts(self.new_damage_taken)

        # only run this every three steps
        if iteration % 3:
            return
        enemies_in_base = self.bot.enemy_units.filter(lambda unit: unit.type_id not in {UnitTypeId.OBSERVER, UnitTypeId.SCV}).in_distance_of_group(self.bot.structures, 20)
        logger.info(f"enemies in base {enemies_in_base}")

        mount_defense = len(enemies_in_base) > 0
        mount_offense = not mount_defense and (self.bot.supply_used >= 180 or self.bot.supply_army / self.offense_start_supply > 0.7)

        if mount_offense:
            if self.offense_start_supply == 200:
                self.offense_start_supply = self.bot.supply_army
            await self.bot.chat_send("time to attack")
        else:
            self.offense_start_supply = 200

        squad: FormationSquad
        for i, squad in enumerate(self.squads):
            if not squad.units:
                logger.debug(f"squad {squad} is empty")
                continue
            squad.draw_debug_box()
            squad.update_formation()
            if mount_defense:
                logger.info(f"squad {squad.name} mounting defense")
                await squad.attack(enemies_in_base)
            elif mount_offense:
                logger.info(f"squad {squad.name} mounting offense")
                if self.enemy.enemies_in_view:
                    await squad.attack(self.enemy.enemies_in_view)
                elif self.bot.enemy_structures:
                    await squad.attack(self.bot.enemy_structures)
                else:
                    await squad.attack(self.bot.enemy_start_locations[0])
            else:
                logger.info(f"squad {squad} staging")
                enemy_position = self.bot.enemy_start_locations[0]
                squad.staging_location = self.bot.townhalls.closest_to(enemy_position).position.towards_with_random_angle(enemy_position, 4, math.pi / 2)
                facing = self.get_facing(squad.staging_location, enemy_position)
                await squad.move(squad.staging_location, facing)

        self.report()
        self.new_damage_taken.clear()

    def get_squad_request(self, remaining_cap: int) -> list[UnitTypeId]:
        # squad_to_fill: BaseSquad = None
        squad_type: SquadType = None
        new_supply = 0
        new_units: list[UnitTypeId] = self.scouting.needed_unit_types()
        for unit_type in new_units:
            new_supply += self.bot.calculate_supply_cost(unit_type)

        unmatched_friendlies, unmatched_enemies = self.simulate_battle()
        logger.info(f"simulated battle results: friendlies {self.count_units_by_type(unmatched_friendlies)}, enemies {self.count_units_by_type(unmatched_enemies)}")
        while new_supply < remaining_cap:
            squad_type: SquadType = None
            if unmatched_enemies:
                # type_summary = self.count_units_by_type(unmatched_enemies)
                property_summary = self.count_units_by_property(unmatched_enemies)
                # pick a squad type
                if property_summary['flying'] >= property_summary['ground']:
                    squad_type = SquadTypeDefinitions['anti air']
                else:
                    squad_type = SquadTypeDefinitions['tanks with support']
            elif unmatched_friendlies:
                # seem to be ahead,
                squad_type = SquadTypeDefinitions['banshee harass']
            else:
                squad_type = SquadTypeDefinitions['tanks with support']
            for unit_type in squad_type.composition.current_units:
                new_units.append(unit_type)
                new_supply += self.bot.calculate_supply_cost(unit_type)

        logger.info(f"new_supply: {new_supply} remaining_cap: {remaining_cap}")
        logger.info(f"military requesting {new_units}")
        return new_units

    def simulate_battle(self):
        remaining_dps: dict[int, float] = {}
        remaining_health: dict[int, float] = {}

        enemy_units: Units = self.enemy.get_enemies().filter(lambda unit: not unit.is_structure)
        unmatched_enemies: Units = enemy_units.copy()
        unmatched_friendlies: Units = self.bot.units.copy()
        unattackable_enemies: Units = Units([], bot_object=self.bot)
        unattackable_friendly_tags = unmatched_friendlies.tags

        # simulate all units attacking each other
        # do multiple passes until one side has no units left
        while unmatched_enemies and unmatched_friendlies:
            logger.debug(f"enemies: {unmatched_enemies}")
            logger.debug(f"friendlies: {unmatched_friendlies}")
            remaining_enemies: Units = unmatched_enemies.copy()
            remaining_friendlies: Units = unmatched_friendlies.copy()
            unmatched_enemies.clear()
            unmatched_friendlies.clear()
            remaining_dps.clear()
            enemy_unit: Unit
            for enemy_unit in remaining_enemies:
                if enemy_unit.is_hallucination:
                    continue
                # init enemy health
                if enemy_unit.tag not in remaining_health:
                    logger.debug(f"adding enemy with health {enemy_unit} - {enemy_unit.health}")
                    remaining_health[enemy_unit.tag] = enemy_unit.health
                elif remaining_health[enemy_unit.tag] <= 0:
                    # will be useful when doing multiple passes
                    continue
                enemy_can_be_attacked = False

                # match to friendlies that can attack them
                for friendly_unit in remaining_friendlies:
                    # init friendly health
                    if friendly_unit.tag not in remaining_health:
                        logger.debug(f"adding friendly with health {friendly_unit} - {friendly_unit.health}")
                        remaining_health[friendly_unit.tag] = friendly_unit.health
                    elif remaining_health[friendly_unit.tag] <= 0:
                        continue

                    if self.can_attack(friendly_unit, enemy_unit):
                        enemy_can_be_attacked = True
                        # init friendly dps
                        if friendly_unit.tag not in remaining_dps:
                            # approximation since dps will differ by target
                            remaining_dps[friendly_unit.tag] = friendly_unit.calculate_dps_vs_target(enemy_unit)
                        if remaining_dps[friendly_unit.tag] > 0:
                            smaller_amount = min(remaining_health[enemy_unit.tag], remaining_dps[friendly_unit.tag])
                            remaining_health[enemy_unit.tag] -= smaller_amount
                            remaining_dps[friendly_unit.tag] -= smaller_amount
                            logger.debug(f"subtracting {smaller_amount} from enemy health {enemy_unit}:{remaining_health[enemy_unit.tag]} and friendly dps  - {friendly_unit}{remaining_dps[friendly_unit.tag]}")

                    if self.can_attack(enemy_unit, friendly_unit):
                        if friendly_unit.tag in unattackable_friendly_tags:
                            unattackable_friendly_tags.remove(friendly_unit.tag)
                        # init enemy dps
                        if enemy_unit.tag not in remaining_dps:
                            remaining_dps[enemy_unit.tag] = enemy_unit.calculate_dps_vs_target(friendly_unit)
                        if remaining_dps[enemy_unit.tag] > 0:
                            smaller_amount = min(remaining_health[friendly_unit.tag], remaining_dps[enemy_unit.tag])
                            remaining_health[friendly_unit.tag] -= smaller_amount
                            remaining_dps[enemy_unit.tag] -= smaller_amount
                            logger.debug(f"subtracting {smaller_amount} from friendly health {friendly_unit}:{remaining_health[friendly_unit.tag]} and enemy dps  - {enemy_unit}{remaining_dps[enemy_unit.tag]}")

                    if remaining_health[enemy_unit.tag] == 0:
                        break
                else:
                    logger.debug(f"no matching friendlies for {enemy_unit}")
                    unmatched_enemies.append(enemy_unit)
                if not enemy_can_be_attacked:
                    logger.info(f"unattackable enemy {enemy_unit}")
                    unattackable_enemies.append(enemy_unit)

            for friendly_unit in remaining_friendlies:
                if friendly_unit.tag not in remaining_health or remaining_health[friendly_unit.tag] > 0:
                    logger.debug(f"no matching enemies for {friendly_unit}")
                    unmatched_friendlies.append(friendly_unit)
            if unattackable_enemies or unattackable_friendly_tags:
                logger.info(f"unattackables: {unattackable_enemies} {unattackable_friendly_tags}")
                # stalemate of stuff that can't attack (not considering abilities)
                break
        return (unmatched_friendlies, unmatched_enemies)

    def can_attack(self, source: Unit, target: Unit):
        return source.can_attack_ground and not target.is_flying or (
            source.can_attack_air and (target.is_flying or target.type_id == UnitTypeId.COLOSSUS))

    def count_units_by_type(self, units: Units) -> dict[UnitTypeId, int]:
        counts: dict[UnitTypeId, int] = {}

        for unit in units:
            if unit.is_hallucination:
                continue
            if unit.type_id not in counts:
                counts[unit.type_id] = 1
            else:
                counts[unit.type_id] = counts[unit.type_id] + 1

        return counts

    def count_units_by_property(self, units: Units) -> dict[UnitTypeId, int]:
        counts: dict[UnitTypeId, int] = {
            'flying': 0,
            'ground': 0,
            'armored': 0,
            'biological': 0,
            'hidden': 0,
            'light': 0,
            'mechanical': 0,
            'psionic': 0,
            'attacks ground': 0,
            'attacks air': 0,
        }

        unit: Unit
        for unit in units:
            if unit.is_hallucination:
                continue
            if unit.is_flying:
                counts['flying'] += 1
            else:
                counts['ground'] += 1
            if unit.is_armored:
                counts['armored'] += 1
            if unit.is_biological:
                counts['biological'] += 1
            if unit.is_burrowed or unit.is_cloaked or not unit.is_visible:
                counts['hidden'] += 1
            if unit.is_light:
                counts['light'] += 1
            if unit.is_mechanical:
                counts['mechanical'] += 1
            if unit.is_psionic:
                counts['psionic'] += 1
            if unit.can_attack_ground:
                counts['attacks ground'] += 1
            if unit.can_attack_air:
                counts['attacks air'] += 1

        return counts

    def report(self):
        _report = "[==MILITARY==] "
        for squad in self.squads:
            _report += squad.get_report() + ", "
        _report += self.main_army.get_report()
        logger.info(_report)

    def update_references(self):
        self.main_army.update_references()
        for squad in self.squads:
            squad.update_references()

    def record_death(self, unit_tag):
        if unit_tag in self.squads_by_unit_tag:
            squad = self.squads_by_unit_tag[unit_tag]
            squad.remove_by_tag(unit_tag)
            del self.squads_by_unit_tag[unit_tag]
            # if squad.state == SquadState.DESTROYED and not isinstance(squad, Scouting):
            #     self.squads.remove(squad)
