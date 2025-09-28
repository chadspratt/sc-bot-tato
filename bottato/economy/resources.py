from __future__ import annotations
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.constants import UnitTypeId

from ..mixins import GeometryMixin, UnitReferenceMixin


class Resources(UnitReferenceMixin, GeometryMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.nodes: Units = Units([], bot)
        self.worker_tags_by_node_tag = {}
        # workers sometimes disappear (gas) so this is more permanent
        self.max_workers_per_node = 0

    @property
    def has_unused_capacity(self):
        for node in self.nodes:
            logger.debug(f"{node} has workers {self.worker_tags_by_node_tag[node.tag]}")
            if self.needed_workers_for_node(node):
                return True
        return False

    def add_node(self, node: Unit) -> bool:
        if node in self.nodes:
            logger.debug(f"node {node} already added")
            return False
        logger.debug(f"added node {node}")
        self.nodes.append(node)
        self.worker_tags_by_node_tag[node.tag] = []
        return True

    def needed_workers_for_node(self, node: Unit):
        logger.debug(
            f"resource node {node} has "
            f"{len(self.worker_tags_by_node_tag[node.tag])}/{self.max_workers_per_node}: "
            f"{self.worker_tags_by_node_tag[node.tag]}"
            f"minerals {node.mineral_contents} gas {node.vespene_contents}"
        )
        if node.mineral_contents == 0 and node.vespene_contents == 0:
            return 0
        return self.max_workers_per_node - len(self.worker_tags_by_node_tag[node.tag])

    def nodes_with_capacity(self) -> Units:
        return self.nodes.filter(
            lambda unit: self.needed_workers_for_node(unit) > 0
        )

    def add_worker(self, worker: Unit) -> Unit:
        if worker is None:
            return None
        candidates = self.nodes.filter(
            lambda unit: self.needed_workers_for_node(unit) > 0
        )
        if candidates.empty or worker.type_id == UnitTypeId.MULE:
            candidates = self.nodes
        node = candidates.closest_to(worker)
        self.worker_tags_by_node_tag[node.tag].append(worker.tag)
        return node

    def add_worker_to_node(self, worker: Unit, node: Unit):
        if worker is None:
            return
        if node.tag not in self.worker_tags_by_node_tag:
            # should be impossible to get here, yet it does and will crash without this
            # get_workers_from_depleted deleting it?
            self.add_node(node)
        self.worker_tags_by_node_tag[node.tag].append(worker.tag)

    def remove_worker(self, exiting_worker: Unit):
        self.remove_worker_by_tag(exiting_worker.tag)

    def remove_worker_by_tag(self, tag: int) -> bool:
        for node_tag in self.worker_tags_by_node_tag.keys():
            if tag in self.worker_tags_by_node_tag[node_tag]:
                self.worker_tags_by_node_tag[node_tag].remove(tag)
                logger.debug(f"removing worker {tag} from {node_tag}")
                return True
        return False

    def update_references(self):
        self.nodes = self.get_updated_unit_references(self.nodes)

    def get_worker_capacity(self) -> int:
        if self.bot.townhalls:
            nodes_near_base = self.nodes.filter(lambda unit: self.closest_distance(unit, self.bot.townhalls) < 8)
            return len(nodes_near_base) * self.max_workers_per_node
        return 0
