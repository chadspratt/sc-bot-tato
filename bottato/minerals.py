from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit

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
