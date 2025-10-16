from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.constants import UnitTypeId
from sc2.position import Point2


from ..mixins import GeometryMixin, UnitReferenceMixin

class ResourceNode(UnitReferenceMixin):
    def __init__(self, node: Unit, max_workers: int, max_mules: int, is_long_distance: bool = False):
        self.node = node
        self.max_workers = max_workers
        self.is_long_distance = is_long_distance
        # workers sometimes disappear (gas) so this is more permanent
        self.worker_tags: list[int] = []
        self.mule_tag: int = None
        self.mining_position: Point2 = None

    def needed_workers(self):
        if self.node.mineral_contents == 0 and self.node.vespene_contents == 0:
            return 0
        return self.max_workers - len(self.worker_tags)

class Resources(UnitReferenceMixin, GeometryMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.nodes: list[ResourceNode] = []
        self.nodes_by_tag: dict[int, ResourceNode] = {}
        self.max_workers_per_node = 0
        self.max_mules_per_node = 0
        self.depleted_resource_worker_tags: list[int] = []

    @property
    def has_unused_capacity(self):
        for node in self.nodes:
            if node.needed_workers() > 0:
                return True
        return False

    def add_node(self, node: Unit, is_long_distance: bool = False) -> bool:
        for resource_node in self.nodes:
            if resource_node.node.tag == node.tag:
                resource_node.is_long_distance = is_long_distance
                return False
        new_node = ResourceNode(node, self.max_workers_per_node, self.max_mules_per_node, is_long_distance)
        self.nodes.append(new_node)
        self.nodes_by_tag[node.tag] = new_node
        return True

    def nodes_with_capacity(self) -> Units:
        return Units([node for node in self.nodes if node.needed_workers() > 0], bot_object=self.bot)

    def add_worker(self, worker: Unit) -> Unit:
        if worker is None:
            return None
        candidates: Units = None
        if worker.type_id == UnitTypeId.MULE:
            # Mules can be assigned to any node regardless of capacity
            candidates = Units([node.node for node in self.nodes if node.mule_tag is None], bot_object=self.bot)
        else:
            most_needed = max([node.needed_workers() for node in self.nodes if not node.is_long_distance])
            if most_needed == 0:
                most_needed = max([node.needed_workers() for node in self.nodes if node.is_long_distance])
            if most_needed > 0:
                # prefer nodes that need the most workers
                candidates = Units([node.node for node in self.nodes if node.needed_workers() == most_needed], bot_object=self.bot)

        if candidates:
            node = candidates.closest_to(worker)
            if worker.type_id == UnitTypeId.MULE:
                self.nodes_by_tag[node.tag].mule_tag = worker.tag
            else:
                self.nodes_by_tag[node.tag].worker_tags.append(worker.tag)
            return node

    def add_worker_to_node(self, worker: Unit, node: Unit) -> bool:
        if worker is None:
            return
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

    def remove_worker(self, exiting_worker: Unit) -> bool:
        return self.remove_worker_by_tag(exiting_worker.tag)

    def remove_worker_by_tag(self, tag: int) -> bool:
        for resource_node in self.nodes:
            if tag in resource_node.worker_tags:
                resource_node.worker_tags.remove(tag)
                return True
        return False

    def update_references(self, units_by_tag: dict[int, Unit]):
        for resource_node in self.nodes:
            try:
                resource_node.node = self.get_updated_unit_reference(resource_node.node, units_by_tag)
            except Exception as e:
                self.nodes.remove(resource_node)
                del self.nodes_by_tag[resource_node.node.tag]
                self.depleted_resource_worker_tags.extend(resource_node.worker_tags)
                return
            if resource_node.node.mineral_contents == 0 and resource_node.node.vespene_contents == 0:
                self.nodes.remove(resource_node)
                del self.nodes_by_tag[resource_node.node.tag]
                self.depleted_resource_worker_tags.extend(resource_node.worker_tags)

    def get_worker_capacity(self) -> int:
        capacity_near_base = [resource_node.max_workers for resource_node in self.nodes if not resource_node.is_long_distance]
        return sum(capacity_near_base)

    def get_workers_from_depleted(self) -> Units:
        workers = Units([self.bot.workers.by_tag(worker_tag) for worker_tag in self.depleted_resource_worker_tags], self.bot)
        self.depleted_resource_worker_tags.clear()
        return workers
