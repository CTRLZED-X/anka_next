from enum import IntEnum


class Direction8(IntEnum):
    """Dofus client direction ordering used by MapPoint."""

    RIGHT = 0
    DOWN_RIGHT = 1
    DOWN = 2
    DOWN_LEFT = 3
    LEFT = 4
    UP_LEFT = 5
    UP = 6
    UP_RIGHT = 7
