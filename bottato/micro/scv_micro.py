from __future__ import annotations

from bottato.micro.base_unit_micro import BaseUnitMicro
from bottato.mixins import GeometryMixin


class SCVMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.9

    @property
    def retreat_health(self) -> float:
        return 0.01
