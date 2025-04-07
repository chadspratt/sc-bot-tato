from loguru import logger

from sc2.bot_ai import BotAI

from .resources import Resources


class Vespene(Resources):
    def __init__(self, bot: BotAI) -> None:
        super().__init__(bot)
        self.max_workers_per_node = 3

    def update_references(self):
        super().update_references()
        for node in self.nodes:
            for worker_tag in self.worker_tags_by_node_tag[node.tag]:
                try:
                    worker = self.bot.workers.by_tag(worker_tag)
                except KeyError:
                    continue
                self.bot.client.debug_box2_out(worker, color="(128, 0, 128)")
                self.bot.client.debug_line_out(worker, node, color="(128, 0, 128)")
            self.bot.client.debug_text_world(f"{len(self.worker_tags_by_node_tag[node.tag])} assigned", node)
            if node.assigned_harvesters != len(self.worker_tags_by_node_tag[node.tag]):
                logger.debug(f"{node} has the wrong number of workers expected {len(self.worker_tags_by_node_tag[node.tag])} actual {node.assigned_harvesters} ({self.worker_tags_by_node_tag[node.tag]})")
