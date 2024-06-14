from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit

from .resources import Resources


class Vespene(Resources):
    def __init__(self, bot: BotAI) -> None:
        super().__init__(bot)
        self.known_gas_building_tags = []
        self.max_workers_per_node = 3

    def add_worker(self, worker: Unit) -> Unit:
        gas_building = super().add_worker(worker)

        if gas_building is not None:
            logger.info(f"assigning worker {worker} to gas {gas_building}")
            worker.smart(gas_building)
        return gas_building

    def add_worker_to_node(self, worker: Unit, node: Unit):
        super().add_worker_to_node(worker, node)

        if worker is not None:
            logger.info(f"assigning worker {worker} to gas {node}")
            worker.smart(node)

    def update_references(self):
        super().update_references()
        self.add_ready_gas_buildings()

    def add_ready_gas_buildings(self):
        for gas_building in self.bot.gas_buildings.ready:
            if gas_building.tag not in self.known_gas_building_tags:
                self.known_gas_building_tags.append(gas_building.tag)
                logger.info(f"adding gas building {gas_building}")
                self.add_node(gas_building)
