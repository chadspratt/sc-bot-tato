from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.ability_id import AbilityId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.build_step import BuildStep
from bottato.economy.workers import Workers
from bottato.squad.squad_type import SquadType, SquadTypeDefinitions
from bottato.squad.base_squad import BaseSquad
from bottato.squad.formation_squad import FormationSquad
from bottato.enemy import Enemy
from bottato.map.map import Map
from bottato.mixins import GeometryMixin, DebugMixin, UnitReferenceMixin, TimerMixin

class Bunker(BaseSquad):
    def __init__(self, bot: BotAI):
        super().__init__(bot=bot, name="bunker", color=(255, 255, 0))
        self.structure = None
    
    def empty(self):
        # command units to exit
        self.structure(AbilityId.UNLOADALL_BUNKER)
        self.units.clear()
    
    def pop(self):
        # command one unit to exit
        if self.units:
            unit = self.units.pop()
            # command unit to exit bunker
            return unit
        return None

    def salvage(self):
        # command to salvage the bunker
        self.structure(AbilityId.SALVAGEBUNKER_SALVAGE)

    def is_built(self):
        return self.structure is not None

    def has_space(self):
        return self.is_built() and len(self.units) < 4

class StuckRescue(BaseSquad, UnitReferenceMixin):
    def __init__(self, bot: BotAI, main_army: FormationSquad, squads_by_unit_tag: dict[int, BaseSquad]):
        super().__init__(bot=bot, name="stuck rescue", color=(255, 0, 255))
        self.main_army = main_army
        self.squads_by_unit_tag: dict[int, BaseSquad] = {}

        self.transport: Unit = None
        self.is_loaded: bool = False
        self.dropoff: Point2 = None

        self.pending_unload: set[int] = set()

    def update_references(self):
        if self.transport:
            try:
                self.transport = self.get_updated_unit_reference(self.transport)
            except self.UnitNotFound:
                self.transport = None
                self.is_loaded = False
                self.dropoff = None

    def rescue(self, stuck_units: List[Unit]):
        if self.pending_unload:
            tags_to_check = list(self.pending_unload)
            for tag in tags_to_check:
                try:
                    unit = self.get_updated_unit_reference_by_tag(tag)
                    self.main_army.recruit(unit)
                    self.squads_by_unit_tag[unit.tag] = self.main_army
                    self.pending_unload.remove(tag)
                except self.UnitNotFound:
                    pass
        if self.is_loaded:
            if not self.transport.passengers_tags:
                self.is_loaded = False
                self.dropoff = None
            else:
                self.dropoff = self.main_army.parent_formation.front_center.towards(self.bot.start_location, 8)
                self.transport.move(self.dropoff)
                if self.transport.distance_to(self.dropoff) < 5:
                    self.transport(AbilityId.UNLOADALLAT, self.transport)
                    for tag in self.transport.passengers_tags:
                        self.pending_unload.add(tag)
            return
        if not stuck_units:
            if self.transport:
                if self.transport.cargo_used > 0:
                    self.is_loaded = True
                else:
                    self.main_army.recruit(self.transport)
                    self.transport = None
                    self.is_loaded = False
            return
        if self.transport is None or self.transport.cargo_used == 0:
            medivacs = self.bot.units(UnitTypeId.MEDIVAC)
            if not medivacs:
                return
            medivacs_with_space = medivacs.filter(lambda unit: unit.cargo_left > 0)
            if not medivacs_with_space:
                return
            closest_medivac = medivacs_with_space.closest_to(stuck_units[0])
            if self.transport is None or self.transport != closest_medivac:
                if self.transport:
                    self.main_army.recruit(self.transport)
                    self.squads_by_unit_tag[self.transport.tag] = self.main_army
                self.transport = closest_medivac
                if self.transport.tag in self.squads_by_unit_tag and self.squads_by_unit_tag[self.transport.tag] is not None:
                    self.squads_by_unit_tag[self.transport.tag].remove(self.transport)
                    self.squads_by_unit_tag[self.transport.tag] = None

        cargo_left = self.transport.cargo_left
        for unit in stuck_units:
            if cargo_left >= unit.cargo_size:
                self.transport(AbilityId.LOAD, unit)
                cargo_left -= unit.cargo_size
            else:
                break
        if cargo_left == self.transport.cargo_left:
            # everything loaded (next frame)
            self.is_loaded = True

class Military(GeometryMixin, DebugMixin, UnitReferenceMixin, TimerMixin):
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
        self.bunker = Bunker(self.bot)
        self.squads_by_unit_tag: dict[int, BaseSquad] = {}
        self.squads: List[BaseSquad] = []
        self.created_squad_type_counts: dict[int, int] = {}
        self.offense_start_supply = 200
        # one squad per enemy in base
        self.countered_enemies: dict[int, FormationSquad] = {}
        self.army_ratio: float = 1.0
        self.status_message = ""
        self.stuck_rescue = StuckRescue(self.bot, self.main_army, self.squads_by_unit_tag)

    def add_to_main(self, unit: Unit) -> None:
        self.main_army.recruit(unit)
        self.squads_by_unit_tag[unit.tag] = self.main_army

    def transfer(self, unit: Unit, from_squad: BaseSquad, to_squad: BaseSquad) -> bool:
        if from_squad == to_squad:
            return True
        from_squad.transfer(unit, to_squad)
        self.squads_by_unit_tag[unit.tag] = to_squad

    def transfer_all(self, from_squad: BaseSquad, to_squad: BaseSquad) -> None:
        for unit in [unit for unit in from_squad.units]:
            self.transfer(unit, from_squad, to_squad)

    def rescue_stuck_units(self, stuck_units: List[Unit]):
        self.stuck_rescue.rescue(stuck_units)

    async def manage_squads(self, iteration: int, blueprints: List[BuildStep]):
        self.start_timer("manage_squads")
        self.main_army.draw_debug_box()
        
        # fill bunker before managing defense
        self.manage_bunker(False)

        # only run this every three steps
        if iteration % 3:
            self.bot.client.debug_text_screen(self.status_message, (0.01, 0.01))
            return
        # scout_types = {UnitTypeId.OBSERVER, UnitTypeId.SCV, UnitTypeId.PROBE, UnitTypeId.DRONE}
        # scouts_in_base = self.bot.enemy_units.filter(lambda unit: unit.type_id in scout_types).in_distance_of_group(self.bot.structures, 25)
        base_structures = self.bot.structures.filter(lambda unit: unit.type_id != UnitTypeId.AUTOTURRET)
        enemies_in_base: Units = Units([], self.bot)
        enemies_in_base.extend(self.bot.enemy_units.filter(lambda unit: base_structures.closest_distance_to(unit) < 25))
        out_of_view_in_base = []
        for enemy in self.enemy.recent_out_of_view():
            if base_structures.closest_distance_to(self.enemy.predicted_position[enemy.tag]) <= 25:
                out_of_view_in_base.append(enemy)
        enemies_in_base.extend(out_of_view_in_base)
        # .filter(lambda unit: unit.type_id not in scout_types)
        # enemy_structures_in_base = self.bot.enemy_structures.filter(lambda unit: unit.type_id not in scout_types).in_distance_of_group(self.bot.structures, 25)
        logger.debug(f"enemies in base {enemies_in_base}")
        defend_with_main_army = False

        # disband squads for missing enemies
        for enemy_tag in [tag for tag in self.countered_enemies.keys()]:
            if enemy_tag not in enemies_in_base.tags:
                defense_squad: FormationSquad = self.countered_enemies[enemy_tag]
                self.transfer_all(defense_squad, self.main_army)
                self.squads.remove(defense_squad)
                del self.countered_enemies[enemy_tag]

        # assign squads to enemies
        for enemy in enemies_in_base:
            defense_squad: FormationSquad
            if enemy.tag in self.countered_enemies:
                defense_squad = self.countered_enemies[enemy.tag]
                await defense_squad.attack(self.enemy.predicted_position[enemy.tag])
                logger.debug(f"defending against {enemy} with {defense_squad}")
            elif defend_with_main_army:
                continue
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
                        available_units = self.main_army.units.of_type(unit_type)
                        if available_units:
                            self.transfer(self.closest_unit_to_unit(enemy, available_units), self.main_army, defense_squad)
                        else:
                            self.transfer_all(defense_squad, self.main_army)
                            del self.countered_enemies[enemy.tag]
                            self.squads.remove(defense_squad)
                            defend_with_main_army = True
                            break
                else:
                    await defense_squad.attack(self.enemy.predicted_position[enemy.tag])
                    logger.debug(f"defending against {enemy} with {defense_squad}")

        # XXX compare army values (((minerals / 0.9) + gas) * supply) / 50
        enemy_value = self.get_army_value(self.enemy.get_army())
        main_army_value = self.get_army_value(self.main_army.units)
        army_is_big_enough = main_army_value > enemy_value * 1.5 or self.bot.supply_used > 160
        army_is_grouped = self.main_army.is_grouped()
        self.army_ratio = main_army_value / max(enemy_value, 1)
        mount_offense = not defend_with_main_army and army_is_big_enough and (self.bot.supply_used >= 110 or self.bot.time > 600)
        self.status_message = f"main_army_value: {main_army_value}\nenemy_value: {enemy_value}\nbigger: {army_is_big_enough}, grouped: {army_is_grouped}\nattacking: {mount_offense}\ndefending: {defend_with_main_army}"
        self.bot.client.debug_text_screen(self.status_message, (0.01, 0.01))

        if mount_offense:
            if self.offense_start_supply == 200:
                self.offense_start_supply = self.bot.supply_army
        else:
            self.offense_start_supply = 200

        self.manage_bunker(mount_offense)
        if self.main_army.units:
            self.main_army.draw_debug_box()
            self.main_army.update_formation()
            if defend_with_main_army:
                logger.debug(f"squad {self.main_army.name} mounting defense")
                await self.main_army.attack(enemies_in_base)
            elif mount_offense:
                logger.debug(f"squad {self.main_army.name} mounting offense")
                army_position = self.main_army.parent_formation.front_center
                target = None
                target_position = None
                if self.enemy.enemies_in_view:
                    target = self.enemy.enemies_in_view
                    target_position = target.closest_to(army_position).position
                elif self.bot.enemy_structures:
                    target = self.bot.enemy_structures
                    target_position = target.closest_to(army_position).position
                else:
                    target = self.bot.enemy_start_locations[0]
                    target_position = target
                if not army_is_grouped:
                    army_center = self.main_army.units.closest_to(self.bot.enemy_start_locations[0]).position
                    facing = self.get_facing(army_center, target_position)
                    await self.main_army.move(army_position, facing, force_move=True, blueprints=blueprints)
                else:
                    if target:
                        await self.main_army.attack(target)
            else:
                logger.debug(f"squad {self.main_army} staging at {self.main_army.staging_location}")
                enemy_position = self.bot.enemy_start_locations[0]
                if len(self.bot.townhalls) > 1:
                    closest_base = self.bot.townhalls.closest_to(enemy_position)
                    second_closest_base = self.bot.townhalls.filter(lambda base: base.tag != closest_base.tag).closest_to(enemy_position)
                    path = self.map.get_path_points(closest_base.position, second_closest_base.position)
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
                await self.main_army.move(self.main_army.staging_location, facing, force_move=True, blueprints=blueprints)

        self.report()
        self.stop_timer("manage_squads")

    def manage_bunker(self, mount_offense: bool):
        if self.bunker.is_built():
            try:
                self.bunker.structure = self.get_updated_unit_reference(self.bunker.structure)
            except self.UnitNotFound:
                self.bunker.structure = None
            if mount_offense:
                for unit in self.bunker.units:
                    self.squads_by_unit_tag[unit.tag] = self.main_army
                self.bunker.transfer_all(self.main_army)
                self.bunker.empty()
            elif self.bot.time < 300:
                for unit in self.main_army.units:
                    if not self.bunker.has_space():
                        break
                    if unit.type_id == UnitTypeId.MARINE:
                        self.transfer(unit, self.main_army, self.bunker)
                        unit.smart(self.bunker.structure)

    def get_counter_units(self, unit: Unit):
        unassigned = [UnitTypeId.STALKER, UnitTypeId.SENTRY, UnitTypeId.ADEPT, UnitTypeId.HIGHTEMPLAR, UnitTypeId.DARKTEMPLAR, UnitTypeId.ARCHON, UnitTypeId.IMMORTAL, UnitTypeId.COLOSSUS, UnitTypeId.DISRUPTOR, UnitTypeId.PHOENIX, UnitTypeId.VOIDRAY, UnitTypeId.ORACLE, UnitTypeId.TEMPEST, UnitTypeId.CARRIER, UnitTypeId.MOTHERSHIP]
        unassigned.extend([UnitTypeId.MARINE, UnitTypeId.MARAUDER, UnitTypeId.GHOST, UnitTypeId.HELLION, UnitTypeId.HELLIONTANK, UnitTypeId.WIDOWMINE, UnitTypeId.CYCLONE, UnitTypeId.THOR, UnitTypeId.VIKINGFIGHTER, UnitTypeId.RAVEN, UnitTypeId.BATTLECRUISER])
        unassigned.extend([UnitTypeId.QUEEN, UnitTypeId.ZERGLING, UnitTypeId.BANELING, UnitTypeId.ROACH, UnitTypeId.RAVAGER, UnitTypeId.HYDRALISK, UnitTypeId.LURKER, UnitTypeId.MUTALISK, UnitTypeId.CORRUPTOR, UnitTypeId.SWARMHOSTMP, UnitTypeId.INFESTOR, UnitTypeId.VIPER, UnitTypeId.ULTRALISK, UnitTypeId.BROODLORD])
        if unit.type_id in (UnitTypeId.LIBERATOR, UnitTypeId.LIBERATORAG, UnitTypeId.WARPPRISM, UnitTypeId.BANSHEE, UnitTypeId.MEDIVAC):
            return [UnitTypeId.VIKINGFIGHTER]
        elif unit.type_id in (UnitTypeId.REAPER, UnitTypeId.SIEGETANK, UnitTypeId.SIEGETANKSIEGED, UnitTypeId.ADEPT, UnitTypeId.ZEALOT, UnitTypeId.ZERGLING):
            return [UnitTypeId.BANSHEE]
        elif unit.type_id in (UnitTypeId.OBSERVER, ):
            return [UnitTypeId.RAVEN, UnitTypeId.VIKINGFIGHTER]
        else:
            return [UnitTypeId.MARINE, UnitTypeId.MARINE]

    def get_squad_request(self, remaining_cap: int) -> list[UnitTypeId]:
        self.start_timer("get_squad_request")
        # squad_to_fill: BaseSquad = None
        squad_type: SquadType = None
        new_supply = 0
        new_units: list[UnitTypeId] = []
        for unit_type in new_units:
            new_supply += self.bot.calculate_supply_cost(unit_type)

        army_summary = self.count_units_by_type(self.bot.units)

        unmatched_friendlies, unmatched_enemies = self.simulate_battle()
        logger.debug(f"simulated battle results: friendlies {self.count_units_by_type(unmatched_friendlies)}, enemies {self.count_units_by_type(unmatched_enemies)}")
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
                squad_type = SquadTypeDefinitions['full army']
            else:
                squad_type = SquadTypeDefinitions['full army']

            for unit_type in squad_type.composition.unit_ids:
                if unit_type not in army_summary:
                    army_summary[unit_type] = 0
                if army_summary[unit_type] > 0:
                    army_summary[unit_type] -= 1
                else:
                    new_units.append(unit_type)
                    new_supply += self.bot.calculate_supply_cost(unit_type)
                    if new_supply > remaining_cap:
                        break

        logger.debug(f"new_supply: {new_supply} remaining_cap: {remaining_cap}")
        logger.debug(f"military requesting {new_units}")
        self.stop_timer("get_squad_request")
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
                    logger.debug(f"unattackable enemy {enemy_unit}")
                    unattackable_enemies.append(enemy_unit)

            for friendly_unit in remaining_friendlies:
                if friendly_unit.tag not in remaining_health or remaining_health[friendly_unit.tag] > 0:
                    logger.debug(f"no matching enemies for {friendly_unit}")
                    unmatched_friendlies.append(friendly_unit)
            if unattackable_enemies or unattackable_friendly_tags:
                logger.debug(f"unattackables: {unattackable_enemies} {unattackable_friendly_tags}")
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
        logger.debug(_report)

    def update_references(self):
        self.start_timer("update_references")
        self.main_army.update_references()
        self.stuck_rescue.update_references()
        for squad in self.squads:
            squad.update_references()
        for unit in self.bot.units:
            if unit.tag in self.squads_by_unit_tag:
                continue
            if unit.tag in self.bunker.units.tags:
                continue
            if unit.type_id in (UnitTypeId.SCV, UnitTypeId.MULE):
                continue
            self.add_to_main(unit)
        self.stop_timer("update_references")

    def record_death(self, unit_tag):
        if unit_tag in self.squads_by_unit_tag:
            squad = self.squads_by_unit_tag[unit_tag]
            if squad:
                squad.remove_by_tag(unit_tag)
            del self.squads_by_unit_tag[unit_tag]
