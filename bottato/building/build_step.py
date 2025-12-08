from sc2.bot_ai import BotAI
from sc2.unit import Unit
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId
from sc2.position import Point2

from bottato.map.map import Map
from bottato.mixins import UnitReferenceMixin, GeometryMixin, TimerMixin
from bottato.economy.workers import Workers
from bottato.economy.production import Production
from bottato.building.special_locations import SpecialLocations
from bottato.enums import BuildResponseCode, RushType


class BuildStep(UnitReferenceMixin, GeometryMixin, TimerMixin):
    unit_in_charge: Unit | None = None
    check_idle: bool = False
    last_cancel_time: float = -10
    start_time: float | None = None
    completed_time: float | None = None
    is_in_progress: bool = False
    interrupted_count: int = 0

    def __init__(self, unit_type: UnitTypeId | UpgradeId, bot: BotAI, workers: Workers, production: Production, map: Map):
        self.bot: BotAI = bot
        self.workers: Workers = workers
        self.production: Production = production
        self.map: Map = map

        self.friendly_name = unit_type.name
        self.builder_type: set[UnitTypeId] = self.production.get_builder_type(unit_type)
        if unit_type == UnitTypeId.REFINERYRICH:
            self.cost = bot.calculate_cost(UnitTypeId.REFINERY)
            self.supply_cost = bot.calculate_supply_cost(UnitTypeId.REFINERY)
        else:
            self.cost = bot.calculate_cost(unit_type)
            if isinstance(unit_type, UpgradeId):
                self.supply_cost = 0
            else:
                self.supply_cost = bot.calculate_supply_cost(unit_type)

    # def __repr__(self) -> str:
    #     return ""

    def update_references(self, units_by_tag: dict[int, Unit]):
        pass

    def draw_debug_box(self):
        pass

    def is_unit_type(self, unit_type_id: UnitTypeId | UpgradeId) -> bool:
        return False

    def is_upgrade_type(self, upgrade_id: UpgradeId) -> bool:
        return False

    def is_unit(self) -> bool:
        return False
    
    def get_unit_type_id(self) -> UnitTypeId | None:
        return None
    
    def get_structure_being_built(self) -> Unit | None:
        return None
    
    def is_same_structure(self, structure: Unit) -> bool:
        return False
    
    def set_unit_being_built(self, unit: Unit):
        pass
    
    def manhattan_distance(self, point: Point2) -> float:
        return 9999
    
    def has_position_reserved(self) -> bool:
        return False

    def get_position(self) -> Point2 | None:
        return None

    async def execute(self, special_locations: SpecialLocations, rush_detected_type: RushType) -> BuildResponseCode:
        # override in subclasses
        return BuildResponseCode.FAILED

    def cancel_construction(self):
        pass

    async def is_interrupted(self) -> bool:
        return False
