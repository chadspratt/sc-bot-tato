import enum


class BuildResponseCode(enum.Enum):
    SUCCESS = 0
    FAILED = 1
    NO_BUILDER = 2
    NO_FACILITY = 3
    NO_TECH = 4
    NO_LOCATION = 5
    NO_RESOURCES = 6
    NO_SUPPLY = 7
    QUEUE_EMPTY = 8
    TOO_CLOSE_TO_ENEMY = 9
    
class UnitAttribute(enum.Enum):
    """
    Unit attributes for SC2 units.
    """

    LIGHT = 0
    BIOLOGICAL = 1
    PSIONIC = 2
    MASSIVE = 3
    MECHANICAL = 4
    ARMORED = 5
    HEROIC = 6
    DETECTOR = 7
    STRUCTURE = 8

class WorkerJobType(enum.Enum):
    IDLE = 0
    MINERALS = 1
    VESPENE = 2
    BUILD = 3
    REPAIR = 4
    ATTACK = 5
    SCOUT = 6

class SquadFormationType(enum.Enum):
    SOLID_CIRCLE = 0
    HOLLOW_CIRCLE = 1
    LINE = 3
    SQUARE = 4
    HOLLOW_HALF_CIRCLE = 5
    COLUMNS = 6
    
class RushType(enum.Enum):
    NONE = 0
    PROXY = 1
    STANDARD = 2