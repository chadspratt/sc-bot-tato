from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.economy.workers import Workers
from bottato.squad.squad_type import SquadType, SquadTypeDefinitions
from bottato.squad.base_squad import BaseSquad
from bottato.squad.scouting import Scouting
from bottato.squad.formation_squad import FormationSquad
from bottato.enemy import Enemy
from bottato.map.map import Map
from bottato.mixins import GeometryMixin, DebugMixin, UnitReferenceMixin


class Military(GeometryMixin, DebugMixin, UnitReferenceMixin):
    def __init__(self, bot: BotAI, enemy: Enemy, map: Map, workers: Workers) -> None:
        self.bot: BotAI = bot
        self.enemy = enemy
        self.map = map
        self.workers = workers
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
        self.created_squad_type_counts: dict[int, int] = {}
        self.offense_start_supply = 200
        self.countered_enemies: dict[int, FormationSquad] = {}
        self.army_ratio: float = 1.0
        self.status_message = ""

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
            self.bot.client.debug_text_screen(self.status_message, (0.01, 0.01))
            return
        # scout_types = {UnitTypeId.OBSERVER, UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE}
        # scouts_in_base = self.bot.enemy_units.filter(lambda unit: unit.type_id in scout_types).in_distance_of_group(self.bot.structures, 25)
        base_structures = self.bot.structures.filter(lambda unit: unit.type_id != UnitTypeId.AUTOTURRET)
        enemies_in_base: Units = self.bot.enemy_units.in_distance_of_group(base_structures, 25)
        for enemy in self.enemy.recent_out_of_view():
            if self.bot.structures.closest_distance_to(self.enemy.predicted_position[enemy.tag]) <= 25:
                enemies_in_base.append(enemy)
        # .filter(lambda unit: unit.type_id not in scout_types)
        # enemy_structures_in_base = self.bot.enemy_structures.filter(lambda unit: unit.type_id not in scout_types).in_distance_of_group(self.bot.structures, 25)
        logger.info(f"enemies in base {enemies_in_base}")
        defend_with_main_army = False

        # disband squads for missing enemies
        tags_to_remove = []
        for enemy_tag in self.countered_enemies:
            if enemy_tag not in enemies_in_base.tags:
                defense_squad: FormationSquad = self.countered_enemies[enemy_tag]
                defense_squad.transfer_all(self.main_army)
                tags_to_remove.append(enemy_tag)
                self.squads.remove(defense_squad)
        for enemy_tag in tags_to_remove:
            del self.countered_enemies[enemy_tag]

        # assign squads to enemies
        for enemy in enemies_in_base:
            if defend_with_main_army:
                break

            defense_squad: FormationSquad
            if enemy.tag in self.countered_enemies:
                defense_squad: FormationSquad = self.countered_enemies[enemy.tag]
            else:
                defense_squad = FormationSquad(self.enemy, self.map, bot=self.bot, name=f"defense{len(self.countered_enemies.keys())}")
                self.squads.append(defense_squad)
                self.countered_enemies[enemy.tag] = defense_squad

            desired_counters: List[UnitTypeId] = self.get_counter_units(enemy)
            current_counters: List[UnitTypeId] = [unit.type_id for unit in defense_squad.units]
            for unit_type in desired_counters:
                if unit_type in current_counters:
                    current_counters.remove(unit_type)
                else:
                    if not self.main_army.transfer_by_type(unit_type, defense_squad):
                        defense_squad.transfer_all(self.main_army)
                        self.squads.remove(defense_squad)
                        del self.countered_enemies[enemy.tag]
                        defend_with_main_army = True
                        break
            else:
                await defense_squad.attack(self.enemy.predicted_position[enemy.tag])
                logger.info(f"defending against {enemy} with {defense_squad}")

        # XXX compare army values (((minerals / 0.9) + gas) * supply) / 50
        enemy_value = self.get_army_value(self.enemy.get_army())
        main_army_value = self.get_army_value(self.main_army.units)
        army_is_bigger = main_army_value > enemy_value * 1.5
        army_is_grouped = self.main_army.is_grouped()
        self.army_ratio = main_army_value / max(enemy_value, 1)
        mount_offense = not defend_with_main_army and army_is_bigger and army_is_grouped and (self.bot.supply_used >= 110 or self.bot.time > 600)
        self.status_message = f"main_army_value: {main_army_value}\nenemy_value: {enemy_value}\nbigger: {army_is_bigger}, grouped: {army_is_grouped}\nattacking: {mount_offense}"
        self.bot.client.debug_text_screen(self.status_message, (0.01, 0.01))

        if mount_offense:
            if self.offense_start_supply == 200:
                self.offense_start_supply = self.bot.supply_army
                # await self.bot.chat_send("time to attack")
        else:
            self.offense_start_supply = 200

        # squad: FormationSquad
        # for i, squad in enumerate(self.squads):
        if self.main_army.units:
            self.main_army.draw_debug_box()
            self.main_army.update_formation()
            if defend_with_main_army:
                logger.info(f"squad {self.main_army.name} mounting defense")
                await self.main_army.attack(enemies_in_base)
            elif mount_offense:
                logger.info(f"squad {self.main_army.name} mounting offense")
                if self.enemy.enemies_in_view:
                    await self.main_army.attack(self.enemy.enemies_in_view)
                elif self.bot.enemy_structures:
                    await self.main_army.attack(self.bot.enemy_structures)
                else:
                    await self.main_army.attack(self.bot.enemy_start_locations[0])
            elif not army_is_grouped:
                army_center = self.main_army.units.center
                enemy_position = self.bot.enemy_start_locations[0]
                facing = self.get_facing(army_center, enemy_position)
                await self.main_army.move(army_center, facing, force_move=True)
            else:
                logger.info(f"squad {self.main_army} staging at {self.main_army.staging_location}")
                enemy_position = self.bot.enemy_start_locations[0]
                if len(self.bot.townhalls) > 1:
                    closest_base = self.bot.townhalls.closest_to(enemy_position)
                    second_closest_base = self.bot.townhalls.filter(lambda base: base.tag != closest_base.tag).closest_to(enemy_position)
                    path = self.map.get_path(closest_base.position, second_closest_base.position)
                    backtrack_distance = 15
                    i = 0
                    while backtrack_distance > 0 and i + 1 < len(path):
                        next_node_distance = path[i].distance_to(path[i + 1])
                        if backtrack_distance <= next_node_distance:
                            self.main_army.staging_location = path[i].towards(path[i + 1], backtrack_distance)
                            break
                        backtrack_distance -= next_node_distance
                        i += 1
                else:
                    self.main_army.staging_location = self.bot.start_location.towards(enemy_position, 5)
                facing = self.get_facing(self.main_army.staging_location, enemy_position)
                await self.main_army.move(self.main_army.staging_location, facing, force_move=True)

        self.report()
        self.new_damage_taken.clear()

    def get_counter_units(self, unit: Unit):
        if unit.type_id in (UnitTypeId.LIBERATOR, UnitTypeId.LIBERATORAG, UnitTypeId.WARPPRISM, UnitTypeId.BANSHEE, UnitTypeId.MEDIVAC):
            return [UnitTypeId.VIKINGFIGHTER]
        elif unit.type_id in (UnitTypeId.REAPER, UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED, UnitTypeId.ADEPT, UnitTypeId.ZEALOT, UnitTypeId.ZERGLING):
            return [UnitTypeId.BANSHEE]
        elif unit.type_id in (UnitTypeId.OBSERVER, ):
            return [UnitTypeId.RAVEN, UnitTypeId.VIKINGFIGHTER]
        else:
            return [UnitTypeId.MARINE, UnitTypeId.MARINE]

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
                    squad_type = SquadTypeDefinitions['full army']
            elif unmatched_friendlies:
                # seem to be ahead,
                squad_type = SquadTypeDefinitions['banshee harass']
            else:
                squad_type = SquadTypeDefinitions['full army']
            for unit_type in squad_type.composition.unit_ids:
                new_units.append(unit_type)
                new_supply += self.bot.calculate_supply_cost(unit_type)

        logger.info(f"new_supply: {new_supply} remaining_cap: {remaining_cap}")
        logger.info(f"military requesting {new_units}")
        return new_units

    def simulate_battle(self):
        remaining_dps: dict[int, float] = {}
        remaining_health: dict[int, float] = {}

        unmatched_enemies: Units = self.enemy.get_enemies().filter(lambda unit: not unit.is_structure)
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
