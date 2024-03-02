from typing import Union
from dataclasses import dataclass
from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2


class BuildStep:
    supply_count: int
    unit_type_id: UnitTypeId
    is_in_progress: bool
    unit_in_charge: Unit
    pos: Union[Unit, Point2]

    def __init__(
        self,
        supply_count,
        unit_type_id,
        pos=None
    ):
        self.supply_count = supply_count
        self.unit_type_id = unit_type_id
        self.pos = pos

    async def execute(self, bot: BotAI):
        if (is_structure(unit_type_id)):
            building_pos = get_building_pos(unit_type_id, bot)
        Unit

    async def get_building_pos(unit_type_id: UnitTypeId, bot: BotAI):
        map_center = bot.game_info.map_center
        position_towards_map_center = bot.start_location.towards(map_center, distance=5)
        placement_position = await bot.find_placement(unit_type_id, near=position_towards_map_center, placement_step=1)
        # Can return None if no position was found
        if placement_position:

    def is_structure() -> bool:
        
