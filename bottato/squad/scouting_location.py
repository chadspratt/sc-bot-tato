from sc2.position import Point2

class ScoutingLocation:
    def __init__(self, position: Point2):
        self.position: Point2 = position
        self.last_seen: float = 0
        self.last_visited: float = 0
        self.is_occupied_by_enemy: bool = False

    def __repr__(self) -> str:
        return f"ScoutingLocation({self.position})"

    def needs_fresh_scouting(self, current_time: float, skip_occupied: bool) -> bool:
        if self.is_occupied_by_enemy:
            if skip_occupied:
                return False
            return (current_time - self.last_seen) > 20
        return (current_time - self.last_visited) > 20
