# Elevator Controller

## The Problem

Elevator software is safety-critical. The two properties that must never be violated: doors must not open while the elevator is moving, and the elevator must never travel past the top or bottom floor. A bug in either property can cause physical harm — passengers stepping into an open shaft, or the car crashing into the pit.

These invariants seem easy to maintain, but the complexity comes from the interaction between subsystems. The door controller, motion controller, and request scheduler must coordinate. A race condition where the motion controller starts moving before the door controller confirms closure is exactly the kind of bug that passes a unit test (where operations are sequential) but fails in production (where events are asynchronous).

## The Implementation

`elevator.py` — An `ElevatorController` using:
- **`enum.IntEnum`** for motion and door states
- **`collections.deque`** for the request queue
- **Callback system** for floor arrival events

Key safety interlocks:
- `open_doors()` checks `motion == STOPPED` before opening
- `move_up()/move_down()` checks `doors == CLOSED` before moving
- `emergency_stop()` immediately halts motion

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/elevator/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    elevator,
    ElevatorSpec,
    state_extractor=lambda self: {
        'floor': self._floor, 'min_floor': self.min_floor,
        'max_floor': self.max_floor,
        'motion': self._motion.value, 'doors': self._doors.value,
    },
    operations=[
        lambda e: e.open_doors(),
        lambda e: e.close_doors(),
        lambda e: e.move_to_floor(random.randint(1, 10)),
        lambda e: e.emergency_stop(),
    ],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    ElevatorController,
    ElevatorSpec,
    state_extractor=lambda self: {
        'floor': self._floor, 'min_floor': self.min_floor,
        'max_floor': self.max_floor,
        'motion': self._motion.value, 'doors': self._doors.value,
    },
    methods=["open_doors", "close_doors", "move_to_floor", "emergency_stop"],
    mode="enforce",  # safety-critical: raise on violation
)
```

### 4. Per-method decorators (legacy, still supported)

Every safety-critical method is currently decorated with `@runtime_guard`:

```python
@runtime_guard(ElevatorSpec, state_extractor=lambda self: {
    'floor': self._floor, 'min_floor': self.min_floor,
    'max_floor': self.max_floor,
    'motion': self._motion.value, 'doors': self._doors.value,
})
def open_doors(self) -> None: ...
```

After every call, the guard verifies that the floor is within bounds, doors are closed when moving, and the motion state is valid. An `AssertionError` fires immediately if any safety invariant is violated.

## The Spec

`spec_elevator.py` enforces three invariants:

1. **`floor_in_bounds`**: `min_floor <= floor <= max_floor`
2. **`doors_closed_when_moving`**: `motion > 0 → doors == 0`
3. **`motion_valid`**: Motion state is always 0, 1, or 2

## The Bug Praxis Catches

In `broken/spec_elevator.py`, `move_up` is missing `require(self.doors == 0)`:

```python
@transition
def move_up(self, dummy: BoundedInt[0, 0]):
    # Missing: require(self.doors == 0)
    require(self.motion == 0)
    require(self.floor + 1 <= self.max_floor)
    self.motion = 1
    self.floor += 1
```

Praxis finds: elevator at floor 1 with doors open, starts moving up — doors are open while motion is active. A critical safety violation.

## Run It

```bash
pytest examples/real_world/elevator/ -v
praxis check examples/real_world/elevator/
praxis check examples/real_world/elevator/broken/
```
