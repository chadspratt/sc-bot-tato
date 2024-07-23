import math
from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from .squad.squad_type import SquadType, SquadTypeDefinitions
from .squad.base_squad import BaseSquad, SquadState
from .squad.scouting import Scouting
from .squad.formation_squad import FormationSquad
from .enemy import Enemy

from .mixins import GeometryMixin, DebugMixin


class Military(GeometryMixin, DebugMixin):
    def __init__(self, bot: BotAI, enemy: Enemy) -> None:
        self.bot: BotAI = bot
        self.enemy = enemy
        self.unassigned_army = FormationSquad(
            bot=bot,
            enemy=enemy,
            type=SquadTypeDefinitions['none'],
            color=self.random_color(),
            name='unassigned'
        )
        self.scouting = Scouting(self.bot, enemy, self.random_color())
        self.new_damage_taken: dict[int, float] = {}
        self.squads_by_unit_tag: dict[int, BaseSquad] = {}
        self.squads: List[BaseSquad] = []
        self.squads.append(self.unassigned_army)
        self.created_squad_type_counts: dict[int, int] = {}
        self.last_offense_push = 0
        self.last_defense_push = 0

    def add_squad(self, squad_type: SquadType) -> FormationSquad:
        new_squad = FormationSquad(bot=self.bot,
                                   type=squad_type,
                                   enemy=self.enemy,
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

    async def manage_squads(self):
        self.unassigned_army.draw_debug_box()
        for unassigned in self.unassigned_army.units:
            if self.scouting.needs(unassigned):
                logger.info(f"scouts needed: {self.scouting.scouts_needed}")
                self.unassigned_army.transfer(unassigned, self.scouting)
                self.squads_by_unit_tag[unassigned.tag] = self.scouting
                continue
            for squad in self.squads:
                if squad.needs(unassigned):
                    self.unassigned_army.transfer(unassigned, squad)
                    self.squads_by_unit_tag[unassigned.tag] = squad
                    break

        self.scouting.update_visibility()
        await self.scouting.move_scouts(self.new_damage_taken)

        enemies_in_base: Units = Units([], bot_object=self.bot)
        logger.info(f"damaged unit tags {self.new_damage_taken.keys()}")
        for unit_id in self.new_damage_taken.keys():
            try:
                unit: Unit = self.bot.structures.by_tag(unit_id)
            except KeyError:
                # structure already destroyed, ignore it
                continue
            new_enemies = self.bot.enemy_units.closest_n_units(unit, 5)
            logger.info(f"enemies attacking {unit}: {new_enemies}")
            enemies_in_base.extend(new_enemies)
        logger.info(f"enemies in base {enemies_in_base}")

        mount_defense = enemies_in_base
        # time_since_last_push = self.bot.time - self.last_offense_push
        # mount_offense = time_since_last_push < 50 or time_since_last_push > 500 or self.bot.supply_used == 200
        mount_offense = False
        if mount_defense:
            self.last_defense_push = self.bot.time
        if mount_offense:
            self.last_offense_push = self.bot.time

        squad: FormationSquad
        for i, squad in enumerate(self.squads):
            if not squad.units:
                logger.debug(f"squad {squad} is empty")
                continue
            squad.draw_debug_box()
            squad.update_formation()
            if mount_defense:
                logger.info(f"squad {squad} mounting defense")
                await squad.attack(enemies_in_base)
            elif squad.state in (SquadState.FILLING, SquadState.RESUPPLYING) or squad.name == 'unassigned':
                logger.info(f"squad {squad} staging")
                enemy_position = self.bot.enemy_start_locations[0]
                if not squad.staging_location:
                    squad.staging_location = self.bot.townhalls.ready.closest_to(enemy_position).position.towards_with_random_angle(enemy_position, 2, math.pi / 2)
                facing = self.get_facing(squad.staging_location, enemy_position)
                await squad.move(squad.staging_location, facing)
            elif mount_offense:
                logger.info(f"squad {squad} mounting offense")
                if self.enemy.enemies_in_view:
                    await squad.attack(self.enemy.enemies_in_view)
                elif self.bot.enemy_structures:
                    await squad.attack(self.bot.enemy_structures)
                else:
                    await squad.attack(self.bot.enemy_start_locations[0])
            else:
                logger.info(f"squad {squad} just moving")
                await squad.move(squad._destination, squad.destination_facing)
        if self.enemy.enemies_in_view:
            self.unassigned_army.attack(self.enemy.enemies_in_view)

        self.report()
        self.new_damage_taken.clear()

    def get_squad_request(self) -> BaseSquad:
        squad_to_fill: BaseSquad = None
        simplify = True
        if self.scouting.needed_unit_types():
            squad_to_fill = self.scouting
        else:
            if self.bot.time < 250:
                squad_type = SquadTypeDefinitions["early marines"]
            elif simplify:
                squad_type = SquadTypeDefinitions["early marines"]
            else:
                squad_type: SquadType = None
                unmatched_friendlies, unmatched_enemies = self.simulate_battle()
                logger.info(f"simulated battle results: friendlies {self.count_units_by_type(unmatched_friendlies)}, enemies {self.count_units_by_type(unmatched_enemies)}")

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

            # look for incomplete squad
            for squad in self.squads:
                if squad.type.name == squad_type.name:
                    squad_to_fill = squad
                    if squad.needed_unit_types():
                        break
            else:
                squad_to_fill = self.add_squad(squad_type)

        logger.info(f"military requesting {squad_to_fill}")
        return squad_to_fill

    def simulate_battle(self):
        remaining_dps: dict[int, float] = {}
        remaining_health: dict[int, float] = {}

        all_enemies: Units = self.enemy.get_enemies()
        unmatched_enemies: Units = all_enemies
        unmatched_friendlies: Units = self.bot.units

        # simulate all units attacking each other
        # do multiple passes until one side has no units left
        while unmatched_enemies and unmatched_friendlies:
            unmatched_enemies.clear()
            unmatched_friendlies.clear()
            enemy_unit: Unit
            for enemy_unit in all_enemies:
                if enemy_unit.is_hallucination:
                    continue
                # init enemy health
                if enemy_unit.tag not in remaining_health:
                    remaining_health[enemy_unit.tag] = enemy_unit.health
                elif remaining_health[enemy_unit.tag] <= 0:
                    # will be useful when doing multiple passes
                    continue

                nearest_friendlies = self.bot.units.sorted_by_distance_to(enemy_unit)

                # match to friendlies that can attack them
                for nearest_friendly in nearest_friendlies:
                    # init friendly health
                    if nearest_friendly.tag not in remaining_health:
                        remaining_health[nearest_friendly.tag] = nearest_friendly.health
                    elif remaining_health[nearest_friendly.tag] <= 0 or (nearest_friendly.tag in remaining_dps and remaining_dps[nearest_friendly.tag] <= 0):
                        continue

                    if self.can_attack(nearest_friendly, enemy_unit):
                        # init friendly dps
                        if nearest_friendly.tag not in remaining_dps:
                            # approximation since dps will differ by target
                            remaining_dps[nearest_friendly.tag] = nearest_friendly.calculate_dps_vs_target(enemy_unit)
                        smaller_amount = min(remaining_health[enemy_unit.tag], remaining_dps[nearest_friendly.tag])
                        remaining_health[enemy_unit.tag] -= smaller_amount
                        remaining_dps[nearest_friendly.tag] -= smaller_amount

                        if self.can_attack(enemy_unit, nearest_friendly):
                            # init enemy dps
                            if enemy_unit.tag not in remaining_dps:
                                # approximation since dps will differ by target
                                remaining_dps[enemy_unit.tag] = enemy_unit.calculate_dps_vs_target(nearest_friendly)
                            smaller_amount = min(remaining_health[nearest_friendly.tag], remaining_dps[enemy_unit.tag])
                            remaining_health[nearest_friendly.tag] -= smaller_amount
                            remaining_dps[enemy_unit.tag] -= smaller_amount

                        if remaining_health[enemy_unit.tag] == 0:
                            break
                else:
                    unmatched_enemies.append(enemy_unit)

            for friendly in self.bot.units:
                if remaining_health[friendly.tag] > 0:
                    unmatched_friendlies.append(enemy_unit)
                    if unmatched_enemies:
                        # only care about full list if no remaining enemies
                        break
        return (unmatched_friendlies, unmatched_enemies)

    def can_attack(source: Unit, target: Unit):
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
        _report += self.unassigned_army.get_report()
        logger.info(_report)

    def update_references(self):
        self.unassigned_army.update_references()
        for squad in self.squads:
            squad.update_references()

    def record_death(self, unit_tag):
        if unit_tag in self.squads_by_unit_tag:
            squad = self.squads_by_unit_tag[unit_tag]
            squad.remove_by_tag(unit_tag)
            del self.squads_by_unit_tag[unit_tag]
            if squad.state == SquadState.DESTROYED and not isinstance(squad, Scouting):
                self.squads.remove(squad)
