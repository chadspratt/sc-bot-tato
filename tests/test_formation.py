import math

import pytest

from ..bottato.formation import (
    ParentFormation,
    Formation,
    UnitDemographics,
    FormationType,
)


class SimplePoint2:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class TestParentFormation:
    def test_apply_rotation_eighth(self):
        positions = {
            1: SimplePoint2(1, 0),
        }
        ParentFormation().apply_rotation(positions, math.pi / 4)
        assert positions[1].x == pytest.approx(0.7071, 0.01)
        assert positions[1].y == pytest.approx(-0.7071, 0.01)

    def test_apply_rotation_quarter(self):
        positions = {
            1: SimplePoint2(1, 0),
        }
        ParentFormation().apply_rotation(positions, math.pi / 2)
        assert positions[1].x == pytest.approx(0)
        assert positions[1].y == -1

    def test_apply_rotation_half(self):
        positions = {
            1: SimplePoint2(1, 0),
        }
        ParentFormation().apply_rotation(positions, math.pi)
        assert positions[1].x == -1
        assert positions[1].y == pytest.approx(0)

    def test_apply_rotation_three_quarter(self):
        positions = {
            1: SimplePoint2(1, 0),
        }
        ParentFormation().apply_rotation(positions, 3 * math.pi / 2)
        assert positions[1].x == pytest.approx(0)
        assert positions[1].y == 1

    def test_apply_rotation_full(self):
        positions = {
            1: SimplePoint2(1, 0),
        }
        ParentFormation().apply_rotation(positions, 2 * math.pi)
        assert positions[1].x == 1
        assert positions[1].y == pytest.approx(0)

    def test_apply_rotation_squad_quarter(self):
        positions = {
            1: SimplePoint2(0, 0),
            2: SimplePoint2(1, 1),
            3: SimplePoint2(-1, 1),
            4: SimplePoint2(2, 2),
            5: SimplePoint2(-2, 2),
        }
        ParentFormation().apply_rotation(positions, math.pi / 2)
        assert positions[1].x == pytest.approx(0)
        assert positions[1].y == pytest.approx(0)
        assert positions[2].x == pytest.approx(1)
        assert positions[2].y == pytest.approx(-1)
        assert positions[3].x == pytest.approx(1)
        assert positions[3].y == pytest.approx(1)
        assert positions[4].x == pytest.approx(2)
        assert positions[4].y == pytest.approx(-2)
        assert positions[5].x == pytest.approx(2)
        assert positions[5].y == pytest.approx(2)


class TestFormation:
    def test_hollow_half_circle_placement_underfull(self, monkeypatch):
        def mock_get_unit_demographics(_self):
            demographics = UnitDemographics()
            demographics.minimum_attack_range = 5
            demographics.maximum_unit_radius = 0.5
            return demographics

        monkeypatch.setattr(
            Formation, "get_unit_demographics", mock_get_unit_demographics
        )

        formation = Formation(
            formation_type=FormationType.HOLLOW_HALF_CIRCLE,
            unit_tags=[1, 2, 3, 4, 5, 6],
            offset=SimplePoint2(0, 0),
        )
        print([str(p) for p in formation.positions])
        assert formation.positions[0].offset.x == pytest.approx(0)
        assert formation.positions[0].offset.y == pytest.approx(5)
        assert formation.positions[1].offset.x == pytest.approx(-0.5058416)
        assert formation.positions[1].offset.y == pytest.approx(4.9743466)
        assert formation.positions[2].offset.x == pytest.approx(0.5058416)
        assert formation.positions[2].offset.y == pytest.approx(4.9743466)
        assert formation.positions[3].offset.x == pytest.approx(-1.0064926)
        assert formation.positions[3].offset.y == pytest.approx(4.8976497)
        assert formation.positions[4].offset.x == pytest.approx(1.0064926)
        assert formation.positions[4].offset.y == pytest.approx(4.8976497)
        assert formation.positions[5].offset.x == pytest.approx(-1.4968156)
        assert formation.positions[5].offset.y == pytest.approx(4.7706962)

    def test_hollow_half_circle_placement_overfull(self, monkeypatch):
        def mock_get_unit_demographics(_self):
            demographics = UnitDemographics()
            demographics.minimum_attack_range = 3
            demographics.maximum_unit_radius = 1
            return demographics

        monkeypatch.setattr(
            Formation, "get_unit_demographics", mock_get_unit_demographics
        )

        formation = Formation(
            formation_type=FormationType.HOLLOW_HALF_CIRCLE,
            unit_tags=list(range(22)),
            offset=SimplePoint2(0, 0),
        )
        print([str(p) for p in formation.positions])
        assert formation.positions[0].offset.x == pytest.approx(0.0)
        assert formation.positions[0].offset.y == pytest.approx(3.0)
        assert formation.positions[1].offset.x == pytest.approx(-1.0260604299770062)
        assert formation.positions[1].offset.y == pytest.approx(2.8190778623577253)
        assert formation.positions[2].offset.x == pytest.approx(1.0260604299770062)
        assert formation.positions[2].offset.y == pytest.approx(2.8190778623577253)
        assert formation.positions[3].offset.x == pytest.approx(-1.9283628290596178)
        assert formation.positions[3].offset.y == pytest.approx(2.298133329356934)
        assert formation.positions[4].offset.x == pytest.approx(1.9283628290596178)
        assert formation.positions[4].offset.y == pytest.approx(2.298133329356934)
        assert formation.positions[5].offset.x == pytest.approx(-2.598076211353316)
        assert formation.positions[5].offset.y == pytest.approx(1.5000000000000004)
        assert formation.positions[6].offset.x == pytest.approx(2.598076211353316)
        assert formation.positions[6].offset.y == pytest.approx(1.5000000000000004)
        assert formation.positions[7].offset.x == pytest.approx(-2.954423259036624)
        assert formation.positions[7].offset.y == pytest.approx(0.5209445330007912)
        assert formation.positions[8].offset.x == pytest.approx(2.954423259036624)
        assert formation.positions[8].offset.y == pytest.approx(0.5209445330007912)
        assert formation.positions[9].offset.x == pytest.approx(0.0)
        assert formation.positions[9].offset.y == pytest.approx(4.0)
        assert formation.positions[10].offset.x == pytest.approx(-1.3680805733026749)
        assert formation.positions[10].offset.y == pytest.approx(3.7587704831436337)
        assert formation.positions[11].offset.x == pytest.approx(1.3680805733026749)
        assert formation.positions[11].offset.y == pytest.approx(3.7587704831436337)
        assert formation.positions[12].offset.x == pytest.approx(-2.571150438746157)
        assert formation.positions[12].offset.y == pytest.approx(3.064177772475912)
        assert formation.positions[13].offset.x == pytest.approx(2.571150438746157)
        assert formation.positions[13].offset.y == pytest.approx(3.064177772475912)
        assert formation.positions[14].offset.x == pytest.approx(-3.4641016151377544)
        assert formation.positions[14].offset.y == pytest.approx(2.0000000000000004)
        assert formation.positions[15].offset.x == pytest.approx(3.4641016151377544)
        assert formation.positions[15].offset.y == pytest.approx(2.0000000000000004)
        assert formation.positions[16].offset.x == pytest.approx(-3.939231012048832)
        assert formation.positions[16].offset.y == pytest.approx(0.6945927106677217)
        assert formation.positions[17].offset.x == pytest.approx(3.939231012048832)
        assert formation.positions[17].offset.y == pytest.approx(0.6945927106677217)
        assert formation.positions[18].offset.x == pytest.approx(0.0)
        assert formation.positions[18].offset.y == pytest.approx(5.0)
        assert formation.positions[19].offset.x == pytest.approx(-1.7101007166283435)
        assert formation.positions[19].offset.y == pytest.approx(4.698463103929543)
        assert formation.positions[20].offset.x == pytest.approx(1.7101007166283435)
        assert formation.positions[20].offset.y == pytest.approx(4.698463103929543)
        assert formation.positions[21].offset.x == pytest.approx(-3.2139380484326963)
        assert formation.positions[21].offset.y == pytest.approx(3.83022221559489)
