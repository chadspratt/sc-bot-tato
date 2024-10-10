from loguru import logger

from sc2.bot_ai import BotAI
from sc2.units import Units

from .resources import Resources


class Minerals(Resources):
    def __init__(self, bot: BotAI) -> None:
        super().__init__(bot)
        self.known_townhall_tags = []
        self.max_workers_per_node = 2

    def update_references(self):
        super().update_references()
        self.add_mineral_fields_for_townhalls()

    def record_non_worker_death(self, unit_tag):
        if unit_tag in self.known_townhall_tags:
            self.known_townhall_tags.remove(unit_tag)

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
                if minerals.mineral_contents and self.add_node(minerals):
                    logger.info(f"adding long distance mining node {minerals}")
                    added += 1
                    if added == count:
                        break
        return added

    def get_workers_from_depleted(self) -> Units:
        workers = Units([], self.bot)
        depleted_nodes = []
        for node_tag in self.worker_tags_by_node_tag.keys():
            try:
                self.nodes.by_tag(node_tag)
            except KeyError:
                # XXX nodes have to be in vision? long distance seems to break
                depleted_nodes.append(node_tag)
                for worker_tag in self.worker_tags_by_node_tag[node_tag]:
                    try:
                        workers.append(self.bot.workers.by_tag(worker_tag))
                    except KeyError:
                        # destroyed
                        pass
        for depleted_node in depleted_nodes:
            del self.worker_tags_by_node_tag[depleted_node]
        return workers
