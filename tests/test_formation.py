import math

import pytest

from ..bottato.formation import ParentFormation


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
