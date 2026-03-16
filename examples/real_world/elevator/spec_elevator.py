"""Elevator Controller Spec — safety properties for an elevator system.

Motion: 0=stopped, 1=moving_up, 2=moving_down
Doors: 0=closed, 1=open

Proves:
- Floor is always within building bounds
- Doors only open when elevator is stopped
- Moving elevator always has doors closed
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class ElevatorSpec(Spec):
    """Elevator controller with floor bounds and door safety."""

    floor: BoundedInt[1, 50]
    min_floor: BoundedInt[1, 50]
    max_floor: BoundedInt[1, 50]
    motion: BoundedInt[0, 2]      # 0=stopped, 1=up, 2=down
    doors: BoundedInt[0, 1]       # 0=closed, 1=open

    @invariant
    def floor_in_bounds(self):
        return And(self.floor >= self.min_floor, self.floor <= self.max_floor)

    @invariant
    def doors_closed_when_moving(self):
        """Doors must be closed when elevator is in motion."""
        return implies(self.motion > 0, self.doors == 0)

    @invariant
    def motion_valid(self):
        return And(self.motion >= 0, self.motion <= 2)

    @transition
    def open_doors(self):
        """Open doors — only when stopped."""
        require(self.motion == 0)
        self.doors = 1

    @transition
    def close_doors(self):
        """Close doors."""
        require(self.doors == 1)
        self.doors = 0

    @transition
    def move_up(self):
        """Move up one floor — doors must be closed, not at top."""
        require(self.doors == 0)
        require(self.motion == 0)
        require(self.floor + 1 <= self.max_floor)
        self.motion = 1
        self.floor += 1

    @transition
    def move_down(self):
        """Move down one floor — doors must be closed, not at bottom."""
        require(self.doors == 0)
        require(self.motion == 0)
        require(self.floor - 1 >= self.min_floor)
        self.motion = 2
        self.floor -= 1

    @transition
    def stop(self):
        """Stop the elevator."""
        require(self.motion > 0)
        self.motion = 0
