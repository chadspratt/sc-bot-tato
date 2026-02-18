import math
from loguru import logger
from typing import List

from cython_extensions.geometry import cy_distance_to, cy_towards
from cython_extensions.units_utils import cy_closer_than
from sc2.bot_ai import BotAI
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units

from bottato.economy.resources import (
    WORKERS_PER_LONG_DISTANCE_NODE,
    ResourceNode,
    Resources,
)
from bottato.map.map import Map
from bottato.mixins import timed
from bottato.unit_reference_helper import UnitReferenceHelper


class Minerals(Resources):
    MINING_RADIUS = 1.325
    mineral_type_ids = [
        UnitTypeId.MINERALFIELD, UnitTypeId.MINERALFIELD450, UnitTypeId.MINERALFIELD750,
        UnitTypeId.LABMINERALFIELD, UnitTypeId.LABMINERALFIELD750,
        UnitTypeId.RICHMINERALFIELD, UnitTypeId.RICHMINERALFIELD750,
        UnitTypeId.PURIFIERRICHMINERALFIELD, UnitTypeId.PURIFIERRICHMINERALFIELD750,
        UnitTypeId.PURIFIERMINERALFIELD, UnitTypeId.PURIFIERMINERALFIELD750,
        UnitTypeId.BATTLESTATIONMINERALFIELD, UnitTypeId.BATTLESTATIONMINERALFIELD750
    ]

    def __init__(self, bot: BotAI, map: Map) -> None:
        super().__init__(bot)
        self.map = map

        self.known_townhall_tags: List[int] = []
        self.max_workers_per_node = 2
        self.max_mules_per_node = 1
        # self.mule_tags_by_node_tag = {}
        # self.mining_positions: dict[int, Point2] = {}

    @timed
    def update_references(self):
        super().update_references()
        # remove missing tags
        for node in self.nodes:
            i = len(node.worker_tags) - 1
            while i >= 0:
                if node.worker_tags[i] not in UnitReferenceHelper.units_by_tag:
                    node.worker_tags.pop(i)
                i -= 1
                    
        self.add_mineral_fields_for_townhalls()
        for node in self.nodes:
            self.bot.client.debug_text_3d(
                f"{len(node.worker_tags)}/{node.max_workers if not node.is_long_distance else WORKERS_PER_LONG_DISTANCE_NODE}\n{node.node.tag}",
                node.node.position3d, size=8, color=(255, 255, 255))

    def record_non_worker_death(self, unit_tag: int):
        # townhall destroyed, update all nodes to long distance
        if unit_tag in self.known_townhall_tags:
            self.known_townhall_tags.remove(unit_tag)
            for resource_node in self.nodes:
                if resource_node.is_long_distance:
                    continue
                try:
                    updated_node = self.bot.mineral_field.by_tag(resource_node.node.tag)
                except KeyError:
                    resource_node.is_long_distance = True
                    # node no longer exists? maybe tag changed
                    continue
                landed_townhalls = self.bot.townhalls.filter(lambda th: not th.is_flying)
                if not landed_townhalls or landed_townhalls.closest_distance_to(updated_node) > 15:
                    resource_node.is_long_distance = True

    def add_mineral_fields_for_townhalls(self):
        for townhall in self.bot.townhalls.ready:
            if townhall.is_flying:
                self.record_non_worker_death(townhall.tag)
            elif townhall.tag not in self.known_townhall_tags:
                townhall_in_position = townhall.position.distance_to_closest(self.bot.expansion_locations_list) < 1
                mineral_distance = 8 if townhall_in_position else 15
                self.known_townhall_tags.append(townhall.tag)
                for mineral in cy_closer_than(self.bot.mineral_field, mineral_distance, townhall.position):
                    logger.debug(f"adding mineral patch {mineral}")
                    self.add_node(mineral)
                    self.add_mining_position(mineral, townhall)
                # remove long-distance minerals
                nodes_to_remove = []
                for resource_node in self.nodes:
                    if resource_node.is_long_distance:
                        self.depleted_resource_worker_tags.extend(resource_node.worker_tags)
                        nodes_to_remove.append(resource_node)
                for node in nodes_to_remove:
                    self.nodes.remove(node)

    def add_mining_position(self, mineral_node: Unit, townhall: Unit | None = None):
        resource_node: ResourceNode | None = self.nodes_by_tag.get(mineral_node.tag, None)
        if resource_node:
            townhall_pos: Point2
            if townhall:
                townhall_pos = townhall.position
            else:
                townhall_pos = mineral_node.position.closest(self.bot.expansion_locations_list)
            target = Point2(cy_towards(mineral_node.position, townhall_pos, self.MINING_RADIUS))
            close_minerals = cy_closer_than(self.bot.mineral_field, self.MINING_RADIUS, target)
            for close_mineral in close_minerals:
                if close_mineral.tag != mineral_node.tag:
                    candidates = mineral_node.position.circle_intersection(close_mineral.position, self.MINING_RADIUS)
                    if len(candidates) == 2:
                        target = townhall_pos.closest(candidates)
            resource_node.mining_position = target

    async def add_long_distance_minerals(self, idle_worker_count: int) -> int:
        added = 0
        nodes_to_add = math.ceil(idle_worker_count / WORKERS_PER_LONG_DISTANCE_NODE)
        if self.bot.townhalls:
            candidates = Units([mf for mf in self.bot.mineral_field if mf.tag not in self.nodes_by_tag], self.bot)
            pathable_nodes = Units([], self.bot)
            path_checking_position = await self.map.get_path_checking_position()
            paths_to_check = [[unit, path_checking_position] for unit in candidates]
            if paths_to_check:
                distances = await self.bot.client.query_pathings(paths_to_check)
                for path, distance in zip(paths_to_check, distances):
                    if distance > 0:
                        pathable_nodes.append(path[0])
            sorted_candidates = self.map.sort_units_by_path_distance(self.bot.start_location, pathable_nodes)
            for i in range(nodes_to_add):
                if i >= len(sorted_candidates):
                    break
                closest_node = sorted_candidates[i]
                self.add_node(closest_node)
                self.add_mining_position(closest_node)
                added += 1
        return added

    def add_mule(self, mule: Unit, minerals: Unit):
        for resource_node in self.nodes:
            if resource_node.node.tag == minerals.tag:
                resource_node.mule_tag = mule.tag
                break

    def remove_mule(self, mule: Unit):
        for resource_node in self.nodes:
            if resource_node.mule_tag == mule.tag:
                resource_node.mule_tag = None
                break

    def nodes_with_mule_capacity(self) -> Units:
        return Units([mineral_node.node for mineral_node in self.nodes
                      if mineral_node.mule_tag is None and not mineral_node.is_long_distance
                     ], bot_object=self.bot)
