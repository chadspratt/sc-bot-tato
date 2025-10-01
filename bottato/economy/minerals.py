from loguru import logger

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bottato.mixins import TimerMixin
from .resources import Resources


class Minerals(Resources, TimerMixin):
    MINING_RADIUS = 1.325
    mineral_type_ids = [
        UnitTypeId.MINERALFIELD, UnitTypeId.MINERALFIELD450, UnitTypeId.MINERALFIELD750,
        UnitTypeId.LABMINERALFIELD, UnitTypeId.LABMINERALFIELD750,
        UnitTypeId.RICHMINERALFIELD, UnitTypeId.RICHMINERALFIELD750,
        UnitTypeId.PURIFIERRICHMINERALFIELD, UnitTypeId.PURIFIERRICHMINERALFIELD750,
        UnitTypeId.PURIFIERMINERALFIELD, UnitTypeId.PURIFIERMINERALFIELD750,
        UnitTypeId.BATTLESTATIONMINERALFIELD, UnitTypeId.BATTLESTATIONMINERALFIELD750
    ]

    def __init__(self, bot: BotAI) -> None:
        super().__init__(bot)
        self.known_townhall_tags = []
        self.max_workers_per_node = 2
        self.max_mules_per_node = 1
        self.mule_tags_by_node_tag = {}
        self.mining_positions: dict[int, Point2] = {}

    def update_references(self):
        self.start_timer("minerals.update_references")
        super().update_references()
        self.add_mineral_fields_for_townhalls()
        self.stop_timer("minerals.update_references")

    def record_non_worker_death(self, unit_tag):
        if unit_tag in self.known_townhall_tags:
            self.known_townhall_tags.remove(unit_tag)

    def add_mineral_fields_for_townhalls(self):
        for townhall in self.bot.townhalls.ready:
            if townhall.tag not in self.known_townhall_tags:
                self.known_townhall_tags.append(townhall.tag)
                for mineral in self.bot.mineral_field.closer_than(8, townhall):
                    logger.debug(f"adding mineral patch {mineral}")
                    self.add_node(mineral)
                    target = mineral.position.towards(townhall, self.MINING_RADIUS)
                    close_minerals = self.bot.mineral_field.closer_than(self.MINING_RADIUS + 0.5, target)
                    for close_mineral in close_minerals:
                        if close_mineral.tag != mineral.tag:
                            candidates = mineral.position.circle_intersection(close_mineral.position, self.MINING_RADIUS)
                            if len(candidates) == 2:
                                target = townhall.position.closest(candidates)
                    self.mining_positions[mineral.tag] = target
    def add_long_distance_minerals(self, count: int) -> int:
        added = 0
        if self.bot.townhalls:
            for mineral_node in self.bot.mineral_field.sorted_by_distance_to(self.bot.townhalls[0]):
                if mineral_node.mineral_contents and self.add_node(mineral_node):
                    logger.debug(f"adding long distance mining node {mineral_node}")
                    added += 1
                    if added == count:
                        break
        return added

    def add_mule(self, mule: Unit, minerals: Unit):
        if minerals is not None:
            self.mule_tags_by_node_tag[minerals.tag] = mule.tag

    def remove_mule(self, mule: Unit):
        tags_to_remove = []
        for mineral_tag in self.mule_tags_by_node_tag.keys():
            if self.mule_tags_by_node_tag[mineral_tag] == mule.tag:
                tags_to_remove.append(mineral_tag)
        for tag in tags_to_remove:
            del self.mule_tags_by_node_tag[tag]

    def nodes_with_mule_capacity(self) -> Units:
        return self.nodes.filter(
            lambda mineral_node: mineral_node.tag not in self.mule_tags_by_node_tag
        )

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
            if depleted_node in self.mule_tags_by_node_tag:
                del self.mule_tags_by_node_tag[depleted_node]
        return workers
