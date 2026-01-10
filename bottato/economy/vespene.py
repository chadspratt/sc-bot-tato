from loguru import logger

from sc2.bot_ai import BotAI

from bottato.economy.resources import Resources
from bottato.mixins import timed
from bottato.unit_reference_helper import UnitReferenceHelper


class Vespene(Resources):
    def __init__(self, bot: BotAI) -> None:
        super().__init__(bot)
        self.max_workers_per_node = 3

    @timed
    def update_references(self):
        super().update_references()
        for resource_node in self.nodes:
            for worker_tag in resource_node.worker_tags:
                try:
                    worker = UnitReferenceHelper.get_updated_unit_reference_by_tag(worker_tag)
                except UnitReferenceHelper.UnitNotFound:
                    continue
                self.bot.client.debug_box2_out(worker, color=(128, 0, 128))
                self.bot.client.debug_line_out(worker, resource_node.node, color=(128, 0, 128))
            self.bot.client.debug_text_world(f"{len(resource_node.worker_tags)} assigned", resource_node.node)
            if resource_node.node.assigned_harvesters != len(resource_node.worker_tags):
                logger.debug(f"{resource_node} has the wrong number of workers expected {len(resource_node.worker_tags)} actual {resource_node.node.assigned_harvesters}")