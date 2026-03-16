# Circuit Breaker

## The Problem

When a downstream service goes down, the worst thing your application can do is keep hammering it with requests. Each request times out (30 seconds of blocked threads), the service can't recover because it's flooded, and your application's thread pool is exhausted — a cascading failure that takes down everything.

The circuit breaker pattern solves this: after a threshold of consecutive failures, the circuit "opens" and immediately rejects requests without calling the backend. After a recovery timeout, it transitions to "half-open" and allows one probe request through. If the probe succeeds, the circuit closes and normal traffic resumes.

The critical invariant: a circuit should only be in the OPEN state if failures actually reached the threshold. A bug that opens the circuit prematurely causes unnecessary outages — the backend is fine, but the circuit breaker is rejecting all traffic because a single transient error tripped it.

## The Implementation

`circuit_breaker.py` — A decorator-based `CircuitBreaker` using:
- **`threading.Lock`** for thread-safe state transitions
- **`time.time()`** for recovery timeout tracking
- **`functools.wraps`** to preserve wrapped function metadata

```python
breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

@breaker
def call_external_api():
    return requests.get("https://api.example.com")
```

Features configurable failure/success thresholds, excluded exceptions (e.g., don't count 404s as failures), and runtime statistics.

## The Spec

1. **`valid_state`**: State is always 0 (closed), 1 (open), or 2 (half-open)
2. **`open_means_threshold_reached`**: `state == OPEN → failure_count >= threshold`

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/circuit_breaker/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    breaker,
    CircuitBreakerSpec,
    state_extractor=lambda self: {
        'state': int(self._state),
        'failure_count': self._stats.consecutive_failures,
        'failure_threshold': self.failure_threshold,
    },
    operations=[...],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    CircuitBreaker,
    CircuitBreakerSpec,
    state_extractor=lambda self: {
        'state': int(self._state),
        'failure_count': self._stats.consecutive_failures,
        'failure_threshold': self.failure_threshold,
    },
    methods=["_on_failure", "_on_success", "reset"],
    mode="log",
)
```

### 4. Per-method decorators (legacy, still supported)

The implementation currently uses `@runtime_guard` on `_on_failure`, `_on_success`, and `reset`:

```python
from praxis import runtime_guard

@runtime_guard(CircuitBreakerSpec, state_extractor=lambda self: {
    'state': int(self._state),
    'failure_count': self._stats.consecutive_failures,
    'failure_threshold': self.failure_threshold,
})
def _on_failure(self) -> None: ...
```

If `_on_failure` opens the circuit before the failure count reaches the threshold, the `open_means_threshold_reached` invariant fires immediately.

## The Bug Praxis Catches

In `broken/spec_circuit_breaker.py`, `trip_open` doesn't require the threshold:

```python
@transition
def trip_open(self, dummy: BoundedInt[0, 0]):
    require(self.state == 0)
    # Missing: require(self.failure_count >= self.failure_threshold)
    self.state = 1
```

Praxis finds: `failure_count=0, threshold=1` — circuit opens with zero failures.

## Run It

```bash
pytest examples/real_world/circuit_breaker/ -v
praxis check examples/real_world/circuit_breaker/
praxis check examples/real_world/circuit_breaker/broken/
```
