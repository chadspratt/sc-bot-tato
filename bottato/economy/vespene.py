from loguru import logger

from sc2.bot_ai import BotAI
from sc2.unit import Unit

from bottato.mixins import TimerMixin, UnitReferenceMixin
from bottato.economy.resources import Resources


class Vespene(Resources, TimerMixin, UnitReferenceMixin):
    def __init__(self, bot: BotAI) -> None:
        super().__init__(bot)
        self.max_workers_per_node = 3

    def update_references(self, units_by_tag: dict[int, Unit] | None = None):
        self.start_timer("vespene.update_references")
        super().update_references(units_by_tag)
        for resource_node in self.nodes:
            for worker_tag in resource_node.worker_tags:
                try:
                    worker = self.get_updated_unit_reference_by_tag(worker_tag, self.bot, units_by_tag)
                except self.UnitNotFound:
                    continue
                self.bot.client.debug_box2_out(worker, color=(128, 0, 128))
                self.bot.client.debug_line_out(worker, resource_node.node, color=(128, 0, 128))
            self.bot.client.debug_text_world(f"{len(resource_node.worker_tags)} assigned", resource_node.node)
            if resource_node.node.assigned_harvesters != len(resource_node.worker_tags):
                logger.debug(f"{resource_node} has the wrong number of workers expected {len(resource_node.worker_tags)} actual {resource_node.node.assigned_harvesters}")
        self.stop_timer("vespene.update_references")
