from loguru import logger

from sc2.bot_ai import BotAI
from sc2.units import Units
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2

from bottato.mixins import TimerMixin
from .resources import ResourceNode, Resources


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
        # self.mule_tags_by_node_tag = {}
        # self.mining_positions: dict[int, Point2] = {}

    def update_references(self, units_by_tag: dict[int, Unit]):
        self.start_timer("minerals.update_references")
        super().update_references(units_by_tag)
        # remove missing tags
        if units_by_tag:
            for node in self.nodes:
                i = len(node.worker_tags) - 1
                while i >= 0:
                    if node.worker_tags[i] not in units_by_tag:
                        node.worker_tags.pop(i)
                    i -= 1
                    
        self.add_mineral_fields_for_townhalls()
        self.stop_timer("minerals.update_references")

    def record_non_worker_death(self, unit_tag):
        # townhall destroyed, update all nodes to long distance
        if unit_tag in self.known_townhall_tags:
            self.known_townhall_tags.remove(unit_tag)
            for resource_node in self.nodes:
                if resource_node.is_long_distance:
                    continue
                try:
                    updated_node = self.bot.mineral_field.by_tag(resource_node.node.tag)
                except KeyError:
                    # node no longer exists? maybe tag changed
                    continue
                if not self.bot.townhalls or self.bot.townhalls.closest_distance_to(updated_node) > 15:
                    resource_node.is_long_distance = True

    def add_mineral_fields_for_townhalls(self):
        for townhall in self.bot.townhalls.ready:
            if townhall.tag not in self.known_townhall_tags:
                self.known_townhall_tags.append(townhall.tag)
                for mineral in self.bot.mineral_field.closer_than(8, townhall):
                    logger.debug(f"adding mineral patch {mineral}")
                    self.add_node(mineral, is_long_distance=False)
                    self.add_mining_position(mineral, townhall)

    def add_mining_position(self, mineral_node: Unit, townhall: Unit = None):
        resource_node: ResourceNode = self.nodes_by_tag.get(mineral_node.tag, None)
        if resource_node and resource_node.mining_position is None:
            townhall_pos = None
            if townhall:
                townhall_pos = townhall.position
            else:
                townhall_pos = mineral_node.position.closest(self.bot.expansion_locations_list)
            target = mineral_node.position.towards(townhall_pos, self.MINING_RADIUS)
            close_minerals = self.bot.mineral_field.closer_than(self.MINING_RADIUS, target)
            for close_mineral in close_minerals:
                if close_mineral.tag != mineral_node.tag:
                    candidates = mineral_node.position.circle_intersection(close_mineral.position, self.MINING_RADIUS)
                    if len(candidates) == 2:
                        target = townhall_pos.closest(candidates)
            resource_node.mining_position = target

    def add_long_distance_minerals(self, idle_worker_count: int) -> bool:
        added = False
        if self.bot.townhalls and len(self.nodes) < idle_worker_count / 2:
            for mineral_node in self.bot.mineral_field.sorted_by_distance_to(self.bot.townhalls[0]):
                if mineral_node.mineral_contents and self.add_node(mineral_node, is_long_distance=True):
                    logger.debug(f"adding long distance mining node {mineral_node}")
                    added = True
                    self.add_mining_position(mineral_node)
                    if len(self.nodes) >= idle_worker_count / 2:
                        break
        return added

    def add_mule(self, mule: Unit, minerals: Unit):
        for resource_node in self.nodes:
            if resource_node.node.tag == minerals.tag:
                resource_node.mule_tag = mule.tag
                break

    def remove_mule(self, mule: Unit):
        for resource_node in self.nodes:
            if resource_node.mule_tag == mule.tag:
                resource_node.mule_tag = None
                break

    def nodes_with_mule_capacity(self) -> Units:
        return Units([mineral_node.node for mineral_node in self.nodes
                      if mineral_node.mule_tag is None
                     ], bot_object=self.bot)
