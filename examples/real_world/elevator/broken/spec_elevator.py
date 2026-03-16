"""Broken elevator spec — move_up doesn't close doors first.

Bug: move_up transition doesn't require doors == 0 (closed).
This violates the doors_closed_when_moving invariant — the elevator
can start moving with doors open, which is a critical safety hazard.
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenElevatorSpec(Spec):
    floor: BoundedInt[1, 50]
    min_floor: BoundedInt[1, 50]
    max_floor: BoundedInt[1, 50]
    motion: BoundedInt[0, 2]
    doors: BoundedInt[0, 1]

    @invariant
    def floor_in_bounds(self):
        return And(self.floor >= self.min_floor, self.floor <= self.max_floor)

    @invariant
    def doors_closed_when_moving(self):
        return implies(self.motion > 0, self.doors == 0)

    @transition
    def open_doors(self):
        require(self.motion == 0)
        self.doors = 1

    @transition
    def move_up(self):
        """BUG: Missing require(self.doors == 0)."""
        # Missing: require(self.doors == 0)
        require(self.motion == 0)
        require(self.floor + 1 <= self.max_floor)
        self.motion = 1
        self.floor += 1

    @transition
    def stop(self):
        require(self.motion > 0)
        self.motion = 0
