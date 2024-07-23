from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.units import Units

from .resources import Resources


class Minerals(Resources):
    def __init__(self, bot: BotAI) -> None:
        super().__init__(bot)
        self.known_townhall_tags = []
        self.max_workers_per_node = 2

    def add_worker(self, worker: Unit) -> Unit:
        mineral_field = super().add_worker(worker)

        if mineral_field is not None:
            logger.info(f"assigning worker {worker} to minerals {mineral_field}")
            worker.gather(mineral_field)
        return mineral_field

    def add_worker_to_node(self, worker: Unit, node: Unit):
        super().add_worker_to_node(worker, node)

        if worker is not None:
            logger.info(f"assigning worker {worker} to minerals {node}")
            worker.gather(node)

    def update_references(self):
        super().update_references()
        self.add_mineral_fields_for_townhalls()

    def add_mineral_fields_for_townhalls(self):
        for townhall in self.bot.townhalls.ready:
            if townhall.tag not in self.known_townhall_tags:
                self.known_townhall_tags.append(townhall.tag)
                for mineral in self.bot.mineral_field.closer_than(8, townhall):
                    logger.info(f"adding mineral patch {mineral}")
                    self.add_node(mineral)

    def add_long_distance_minerals(self, count: int) -> int:
        added = 0
        if self.bot.townhalls:
            for minerals in self.bot.mineral_field.sorted_by_distance_to(self.bot.townhalls[0]):
                if self.add_node(minerals):
                    logger.info(f"adding long distance mining node {minerals}")
                    added += 1
                    if added == count:
                        break
        return added

    def get_workers_from_depleted(self) -> Units:
        workers = Units([], self.bot)
        depleted_nodes = Units([], self.bot)
        for node in self.nodes:
            if node.mineral_contents == 0:
                workers.extend(self.worker_tags_by_node_tag[node.tag])
                depleted_nodes.append(node)
        for depleted_node in depleted_nodes:
            del self.worker_tags_by_node_tag[depleted_node.tag]
            self.nodes.remove(depleted_node)
        return workers
