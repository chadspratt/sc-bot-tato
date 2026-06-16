

from sc2.ids.unit_typeid import UnitTypeId
from sc2.position import Point2
from sc2.unit import Unit

from bottato.enums import WorkerJobType


class WorkerAssignment():
    def __init__(self, unit: Unit) -> None:
        self.unit = unit
        self.job_type: WorkerJobType = WorkerJobType.IDLE
        self.target: Unit | None = None
        self.target_position: Point2 | None = None
        self.gather_position: Point2 | None = None
        self.dropoff_target: Unit | None = None
        self.dropoff_position: Point2 | None = None
        self.initial_gather_complete: bool = False
        self.is_returning = False
        self.on_attack_break = False
        self.last_reassign_time: float = 0.0
        self.last_swap_time: float = 0.0
        self.build_type: UnitTypeId | None = None

    def __repr__(self) -> str:
        return f"WorkerAssignment({self.unit}({self.unit_available}), {self.job_type.name}, {self.target})"
    
    @property
    def unit_available(self) -> bool:
        return self.unit is not None and self.unit.age == 0
