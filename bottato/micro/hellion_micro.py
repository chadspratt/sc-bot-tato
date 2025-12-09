from __future__ import annotations

from sc2.unit import Unit

from bottato.unit_types import UnitTypes
from bottato.mixins import GeometryMixin
from bottato.micro.base_unit_micro import BaseUnitMicro


class HellionMicro(BaseUnitMicro, GeometryMixin):
    attack_health: float = 0.4
