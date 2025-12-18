from __future__ import annotations

from bottato.mixins import GeometryMixin
from bottato.micro.base_unit_micro import BaseUnitMicro


class SCVMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.6
