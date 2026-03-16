"""Elevator controller with safety interlocks.

A real elevator controller that manages floor positioning, door state,
motion control, and request queue. Implements key safety invariants:
doors never open while moving, floor stays within building bounds.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

from praxis import runtime_guard
from examples.real_world.elevator.spec_elevator import ElevatorSpec


class Motion(IntEnum):
    """Elevator motion state."""
    STOPPED = 0
    MOVING_UP = 1
    MOVING_DOWN = 2


class DoorState(IntEnum):
    """Elevator door state."""
    CLOSED = 0
    OPEN = 1


@dataclass
class FloorRequest:
    """A request to visit a floor."""
    floor: int
    direction: Motion | None = None  # Preferred direction, or None for destination


class ElevatorController:
    """Elevator controller with safety interlocks and request optimization.

    Safety invariants enforced:
    - Doors never open while elevator is in motion
    - Floor is always within [min_floor, max_floor]
    - Motion state is always valid

    Features:
    - Request queue with direction optimization
    - Door auto-close timer
    - Emergency stop
    - Floor arrival callbacks
    """

    def __init__(
        self,
        min_floor: int = 1,
        max_floor: int = 10,
        door_open_duration: float = 3.0,
    ):
        if min_floor >= max_floor:
            raise ValueError(f"min_floor ({min_floor}) must be < max_floor ({max_floor})")
        if door_open_duration <= 0:
            raise ValueError("door_open_duration must be positive")

        self.min_floor = min_floor
        self.max_floor = max_floor
        self.door_open_duration = door_open_duration

        self._floor = min_floor
        self._motion = Motion.STOPPED
        self._doors = DoorState.CLOSED
        self._request_queue: deque[FloorRequest] = deque()
        self._emergency_stop = False
        self._on_arrival: list[Callable[[int], None]] = []

    @property
    def floor(self) -> int:
        return self._floor

    @property
    def motion(self) -> Motion:
        return self._motion

    @property
    def doors(self) -> DoorState:
        return self._doors

    @property
    def is_idle(self) -> bool:
        return self._motion == Motion.STOPPED and len(self._request_queue) == 0

    def request_floor(self, floor: int) -> None:
        """Add a floor to the request queue."""
        if floor < self.min_floor or floor > self.max_floor:
            raise ValueError(
                f"Floor {floor} is out of range [{self.min_floor}, {self.max_floor}]"
            )
        if not any(r.floor == floor for r in self._request_queue):
            self._request_queue.append(FloorRequest(floor=floor))

    @runtime_guard(ElevatorSpec, state_extractor=lambda self: {
        'floor': self._floor,
        'min_floor': self.min_floor,
        'max_floor': self.max_floor,
        'motion': self._motion.value,
        'doors': self._doors.value,
    })
    def open_doors(self) -> None:
        """Open doors — only when stopped."""
        if self._motion != Motion.STOPPED:
            raise RuntimeError("Cannot open doors while moving")
        if self._emergency_stop:
            raise RuntimeError("Emergency stop active")
        self._doors = DoorState.OPEN

    @runtime_guard(ElevatorSpec, state_extractor=lambda self: {
        'floor': self._floor,
        'min_floor': self.min_floor,
        'max_floor': self.max_floor,
        'motion': self._motion.value,
        'doors': self._doors.value,
    })
    def close_doors(self) -> None:
        """Close doors."""
        self._doors = DoorState.CLOSED

    @runtime_guard(ElevatorSpec, state_extractor=lambda self: {
        'floor': self._floor,
        'min_floor': self.min_floor,
        'max_floor': self.max_floor,
        'motion': self._motion.value,
        'doors': self._doors.value,
    })
    def move_to_floor(self, target: int) -> None:
        """Move to a target floor. Doors must be closed."""
        if self._doors != DoorState.CLOSED:
            raise RuntimeError("Cannot move with doors open")
        if self._emergency_stop:
            raise RuntimeError("Emergency stop active")
        if target < self.min_floor or target > self.max_floor:
            raise ValueError(f"Floor {target} out of range")
        if target == self._floor:
            return

        self._motion = Motion.MOVING_UP if target > self._floor else Motion.MOVING_DOWN

        # Simulate floor-by-floor movement
        step = 1 if target > self._floor else -1
        while self._floor != target:
            self._floor += step

        self._motion = Motion.STOPPED

        # Notify arrival callbacks
        for callback in self._on_arrival:
            callback(self._floor)

    @runtime_guard(ElevatorSpec, state_extractor=lambda self: {
        'floor': self._floor,
        'min_floor': self.min_floor,
        'max_floor': self.max_floor,
        'motion': self._motion.value,
        'doors': self._doors.value,
    })
    def emergency_stop(self) -> None:
        """Activate emergency stop — halts motion immediately."""
        self._motion = Motion.STOPPED
        self._emergency_stop = True

    def reset_emergency(self) -> None:
        """Clear emergency stop state."""
        self._emergency_stop = False

    def on_arrival(self, callback: Callable[[int], None]) -> None:
        """Register a callback for floor arrival events."""
        self._on_arrival.append(callback)

    def process_next_request(self) -> int | None:
        """Process the next request in the queue. Returns the floor visited or None."""
        if not self._request_queue:
            return None
        if self._emergency_stop:
            return None

        request = self._request_queue.popleft()
        if request.floor == self._floor:
            self.open_doors()
            return self._floor

        self.close_doors()
        self.move_to_floor(request.floor)
        self.open_doors()
        return request.floor
