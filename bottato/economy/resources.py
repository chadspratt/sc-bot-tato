from __future__ import annotations
from loguru import logger
from typing import List

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2


from bottato.mixins import GeometryMixin, timed
from bottato.unit_reference_helper import UnitReferenceHelper

class ResourceNode():
    def __init__(self, node: Unit, max_workers: int, max_mules: int, is_long_distance: bool = False):
        self.node = node
        self.max_workers = max_workers
        self.is_long_distance = is_long_distance
        # workers sometimes disappear (gas) so this is more permanent
        self.worker_tags: List[int] = []
        self.mule_tag: int | None = None
        self.mining_position: Point2 | None = None

    def needed_workers(self):
        if self.is_long_distance:
            # put more workers on long distance nodes to compensate for travel time
            return 6 - len(self.worker_tags)
        if not self.node.is_mineral_field and self.node.vespene_contents == 0:
            return 0
        return self.max_workers - len(self.worker_tags)

class Resources(GeometryMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot

        self.nodes: List[ResourceNode] = []
        self.nodes_by_tag: dict[int, ResourceNode] = {}
        self.max_workers_per_node = 0
        self.max_mules_per_node = 0
        self.depleted_resource_worker_tags: List[int] = []

    @property
    def has_unused_capacity(self):
        for node in self.nodes:
            if node.needed_workers() > 0:
                return True
        return False

    def add_node(self, node: Unit) -> bool:
        is_long_distance = True
        for townhall in self.bot.townhalls.ready:
            if townhall.is_flying:
                continue
            if self.bot.get_terrain_height(townhall) == self.bot.get_terrain_height(node):
                if townhall.position.distance_to(node.position) <= 15:
                    is_long_distance = False
                    break
        for resource_node in self.nodes:
            if resource_node.node.tag == node.tag:
                if resource_node.is_long_distance != is_long_distance:
                    resource_node.is_long_distance = is_long_distance
                    for worker_tag in resource_node.worker_tags:
                        worker = self.bot.workers.by_tag(worker_tag)
                return False
        new_node = ResourceNode(node, self.max_workers_per_node, self.max_mules_per_node, is_long_distance)
        self.nodes.append(new_node)
        self.nodes_by_tag[node.tag] = new_node
        return True

    def nodes_with_capacity(self) -> List[ResourceNode]:
        candidates = [node for node in self.nodes if not node.is_long_distance and node.needed_workers() > 0]
        if not candidates:
            candidates = [node for node in self.nodes if node.needed_workers() > 0]
        return candidates

    def add_worker(self, worker: Unit) -> Unit | None:
        if worker is None:
            return None
            
        if not self.nodes:
            logger.warning(f"No resource nodes available for worker {worker}")
            return None

        candidates: Units | None = None
        if worker.type_id == UnitTypeId.MULE:
            # Mules can be assigned to any node regardless of capacity
            candidates = Units([node.node for node in self.nodes if node.mule_tag is None], bot_object=self.bot)
        else:
            # Find nodes that need workers, prioritizing non-long-distance
            nodes_needing_workers = [node for node in self.nodes if not node.is_long_distance and node.needed_workers() > 0]
            if not nodes_needing_workers:
                nodes_needing_workers = [node for node in self.nodes if node.is_long_distance and node.needed_workers() > 0]
            
            if nodes_needing_workers:
                most_needed = max(node.needed_workers() for node in nodes_needing_workers)
                candidates = Units([node.node for node in nodes_needing_workers if node.needed_workers() == most_needed], bot_object=self.bot)

        if candidates:
            node = candidates.closest_to(worker)
            if worker.type_id == UnitTypeId.MULE:
                self.nodes_by_tag[node.tag].mule_tag = worker.tag
            else:
                self.nodes_by_tag[node.tag].worker_tags.append(worker.tag)
            return node
            
        logger.debug(f"No capacity available for worker {worker}")
        return None

    def add_worker_to_node(self, worker: Unit, node: Unit) -> bool:
        if worker is None:
            return False
            
        # Check if node exists in our tracking
        if node.tag not in self.nodes_by_tag:
            # should be impossible to get here, yet it does and will crash without this
            # get_workers_from_depleted deleting it?
            self.add_node(node)
        
        # Check capacity before adding worker (except for mules)
        resource_node = self.nodes_by_tag[node.tag]
        if worker.type_id == UnitTypeId.MULE:
            if resource_node.mule_tag is None:
                resource_node.mule_tag = worker.tag
            else:
                return False
        else:
            if resource_node.needed_workers() > 0:
                resource_node.worker_tags.append(worker.tag)
            else:
                return False

        return True
    
    def get_node_by_worker_tag(self, worker_tag: int) -> ResourceNode | None:
        for resource_node in self.nodes:
            if worker_tag in resource_node.worker_tags:
                return resource_node
        return None

    def remove_worker(self, exiting_worker: Unit) -> bool:
        return self.remove_worker_by_tag(exiting_worker.tag)

    def remove_worker_by_tag(self, tag: int) -> bool:
        for resource_node in self.nodes:
            if tag in resource_node.worker_tags:
                resource_node.worker_tags.remove(tag)
                return True
        return False

    @timed
    def update_references(self):
        nodes_to_remove = []
        
        for resource_node in self.nodes:
            try:
                resource_node.node = UnitReferenceHelper.get_updated_unit_reference(resource_node.node)
            except Exception as e:
                logger.debug(f"Node {resource_node.node.tag} failed to update reference: {e}")
                if not resource_node.node.is_mineral_field:
                    nodes_to_remove.append(resource_node)
                else:
                    for mf in self.bot.mineral_field:
                        if mf.position == resource_node.node.position:
                            resource_node.node = mf
                            self.nodes_by_tag[mf.tag] = resource_node
                            break
                    else:
                        nodes_to_remove.append(resource_node)
                continue
                
            # Check if gas node is depleted
            if not resource_node.node.is_mineral_field and resource_node.node.vespene_contents == 0:
                logger.debug(f"Node {resource_node.node.tag} is depleted")
                nodes_to_remove.append(resource_node)
        
        # Remove all stale/depleted nodes after iteration
        for resource_node in nodes_to_remove:
            self.nodes.remove(resource_node)
            del self.nodes_by_tag[resource_node.node.tag]
            self.depleted_resource_worker_tags.extend(resource_node.worker_tags)

    def get_worker_capacity(self) -> int:
        capacity_near_base = [resource_node.max_workers for resource_node in self.nodes if not resource_node.is_long_distance]
        return sum(capacity_near_base)

    def get_workers_from_depleted(self) -> Units:
        workers = Units([], self.bot)
        for worker_tag in self.depleted_resource_worker_tags:
            try:
                workers.append(self.bot.workers.by_tag(worker_tag))
            except KeyError:
                # not sure why stale tags appear, but ignore them
                continue
        self.depleted_resource_worker_tags.clear()
        return workers
    
    def get_workers_from_overcapacity(self) -> Units:
        workers = Units([], self.bot)
        for resource_node in self.nodes:
            while resource_node.needed_workers() < 0:
                if not resource_node.worker_tags:
                    break
                worker_tag = resource_node.worker_tags.pop()
                try:
                    workers.append(self.bot.workers.by_tag(worker_tag))
                except KeyError:
                    # not sure why stale tags appear, but ignore them
                    continue
        return workers
