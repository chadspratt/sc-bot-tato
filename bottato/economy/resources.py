from __future__ import annotations
from typing import List
from loguru import logger

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.position import Point2

from ..mixins import UnitReferenceMixin


class Resources(UnitReferenceMixin):
    def __init__(self, bot: BotAI) -> None:
        self.bot = bot
        self.nodes: Units = Units([], bot)
        self.worker_tags_by_node_tag = {}
        self.assigned_workers = Units([], bot)
        # workers sometimes disappear (gas) so this is more permanent
        self.assigned_workers_tags: List[int] = []
        self.max_workers_per_node = 0

    @property
    def worker_count(self):
        return len(self.assigned_workers_tags)

    @property
    def available_worker_count(self):
        # some vespene harvesters might not be available if they're in the gas building
        return len(self.assigned_workers)

    @property
    def has_unused_capacity(self):
        for node in self.nodes:
            if self.needed_workers_for_node(node):
                return True
        return False

    def add_node(self, node: Unit) -> bool:
        if node in self.nodes:
            logger.debug(f"node {node} already added")
            return False
        logger.info(f"added node {node} (resets worker tags)")
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
        return self.max_workers_per_node - len(self.worker_tags_by_node_tag[node.tag])

    def add_worker(self, worker: Unit) -> Unit:
        if worker is None:
            return None
        node = self.nodes.filter(
            lambda field: self.needed_workers_for_node(field) > 0
        ).closest_to(worker)
        self.worker_tags_by_node_tag[node.tag].append(worker.tag)
        self.assigned_workers.append(worker)
        self.assigned_workers_tags.append(worker.tag)

        return node

    def add_worker_to_node(self, worker: Unit, node: Unit):
        if worker is None:
            return
        self.worker_tags_by_node_tag[node.tag].append(worker.tag)
        self.assigned_workers.append(worker)
        self.assigned_workers_tags.append(worker.tag)

    def remove_worker(self, exiting_worker: Unit):
        self.assigned_workers.remove(exiting_worker)
        self.remove_worker_by_tag(exiting_worker.tag)

    def remove_worker_by_tag(self, tag: int):
        if tag in self.assigned_workers_tags:
            self.assigned_workers_tags.remove(tag)
            for node_tag in self.worker_tags_by_node_tag.keys():
                if tag in self.worker_tags_by_node_tag[node_tag]:
                    self.worker_tags_by_node_tag[node_tag].remove(tag)
                    logger.info(f"removing worker {tag} from {node_tag}")
                    return

    def transfer_workers_from(self, worker_source: Resources, number_to_move: int):
        workers_moved = 0

        for target_node in self.nodes:
            while self.needed_workers_for_node(target_node) > 0:
                worker = worker_source.take_worker_closest_to(target_node)
                if worker is None:
                    return workers_moved
                self.add_worker_to_node(worker, target_node)
                workers_moved += 1
                if workers_moved == number_to_move:
                    return workers_moved
        return workers_moved

    def take_worker_closest_to(self, target_position: Point2):
        if not self.assigned_workers:
            return None
        exiting_worker = self.assigned_workers.closest_to(target_position)
        self.remove_worker(exiting_worker)
        return exiting_worker

    def update_references(self):
        logger.debug(f"workers before refresh {self.assigned_workers}")
        self.assigned_workers = self.get_updated_unit_references_by_tags(self.assigned_workers_tags)

        logger.debug(f"workers after refresh {self.assigned_workers}")
        self.nodes = self.get_updated_unit_references(self.nodes)

    def get_worker_capacity(self) -> int:
        nodes_near_base = self.nodes.filter(lambda unit: self.bot.townhalls.closest_distance_to(unit) < 8)
        return len(nodes_near_base) * self.max_workers_per_node
