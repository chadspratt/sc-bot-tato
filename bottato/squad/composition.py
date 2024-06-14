from sc2.ids.unit_typeid import UnitTypeId


class Composition():
    def __init__(self, initial_units: list[UnitTypeId], expansion_units: list[UnitTypeId] = [], max_size=0) -> None:
        self.minimum_units = initial_units
        self.expansion_units = expansion_units
        self.current_units = initial_units
        if max_size == 0:
            self.max_size = len(initial_units) + len(expansion_units)
        else:
            self.max_size = max_size

    def count_type(self, type: UnitTypeId) -> int:
        count = 0
        for unit_type in self.current_units:
            if unit_type == type:
                count += 1
        return count
