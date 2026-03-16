"""Circuit breaker pattern for resilient service calls.

A decorator-based circuit breaker that wraps unreliable functions (HTTP calls,
database queries, etc.) and prevents cascading failures by short-circuiting
when a failure threshold is reached.

States:
- CLOSED: Normal operation. Requests pass through. Failures are counted.
- OPEN: Failing. All requests are immediately rejected without calling the backend.
- HALF_OPEN: Testing recovery. One probe request is allowed through.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum
from functools import wraps
from typing import Any, Callable

from praxis import runtime_guard

try:
    from .spec_circuit_breaker import CircuitBreakerSpec
except ImportError:
    import importlib.util, pathlib
    _spec = importlib.util.spec_from_file_location(
        "spec_circuit_breaker", pathlib.Path(__file__).parent / "spec_circuit_breaker.py")
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    CircuitBreakerSpec = _mod.CircuitBreakerSpec


class State(IntEnum):
    """Circuit breaker states."""
    CLOSED = 0
    OPEN = 1
    HALF_OPEN = 2


class CircuitOpenError(Exception):
    """Raised when a call is rejected because the circuit is open."""
    pass


@dataclass
class CircuitStats:
    """Runtime statistics for a circuit breaker."""
    total_calls: int = 0
    total_failures: int = 0
    total_successes: int = 0
    total_rejected: int = 0
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_failure_time: float | None = None
    last_success_time: float | None = None


class CircuitBreaker:
    """Circuit breaker with configurable thresholds and recovery.

    Usage as a decorator:
        breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=30.0)

        @breaker
        def call_external_service():
            return requests.get("https://api.example.com/data")

    Or wrap a function directly:
        result = breaker.call(lambda: requests.get(url))
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        recovery_timeout: float = 30.0,
        excluded_exceptions: tuple[type[Exception], ...] = (),
    ):
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if success_threshold < 1:
            raise ValueError("success_threshold must be at least 1")
        if recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be positive")

        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.recovery_timeout = recovery_timeout
        self.excluded_exceptions = excluded_exceptions

        self._state = State.CLOSED
        self._stats = CircuitStats()
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        """Current circuit state (may auto-transition from OPEN to HALF_OPEN)."""
        with self._lock:
            if self._state == State.OPEN and self._should_attempt_reset():
                self._state = State.HALF_OPEN
            return self._state

    @property
    def stats(self) -> CircuitStats:
        """Current circuit statistics."""
        return self._stats

    def __call__(self, func: Callable) -> Callable:
        """Use as a decorator."""
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return self.call(func, *args, **kwargs)
        wrapper.breaker = self  # type: ignore[attr-defined]
        return wrapper

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute a function through the circuit breaker."""
        with self._lock:
            state = self._state
            if state == State.OPEN:
                if self._should_attempt_reset():
                    self._state = State.HALF_OPEN
                    state = State.HALF_OPEN
                else:
                    self._stats.total_rejected += 1
                    raise CircuitOpenError(
                        f"Circuit is OPEN. "
                        f"{self._stats.consecutive_failures} consecutive failures. "
                        f"Recovery in {self._time_until_recovery():.1f}s"
                    )

        # Execute the call (outside the lock)
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            if isinstance(e, self.excluded_exceptions):
                raise
            self._on_failure()
            raise
        else:
            self._on_success()
            return result

    @runtime_guard(CircuitBreakerSpec, state_extractor=lambda self: {
        'state': int(self._state),
        'failure_count': self._stats.consecutive_failures,
        'failure_threshold': self.failure_threshold,
    })
    def reset(self) -> None:
        """Manually reset the circuit to CLOSED."""
        with self._lock:
            self._state = State.CLOSED
            self._stats.consecutive_failures = 0
            self._stats.consecutive_successes = 0
            self._opened_at = None

    # -- Internal --

    @runtime_guard(CircuitBreakerSpec, state_extractor=lambda self: {
        'state': int(self._state),
        'failure_count': self._stats.consecutive_failures,
        'failure_threshold': self.failure_threshold,
    })
    def _on_success(self) -> None:
        with self._lock:
            self._stats.total_calls += 1
            self._stats.total_successes += 1
            self._stats.consecutive_successes += 1
            self._stats.consecutive_failures = 0
            self._stats.last_success_time = time.time()

            if self._state == State.HALF_OPEN:
                if self._stats.consecutive_successes >= self.success_threshold:
                    self._state = State.CLOSED
                    self._opened_at = None

    @runtime_guard(CircuitBreakerSpec, state_extractor=lambda self: {
        'state': int(self._state),
        'failure_count': self._stats.consecutive_failures,
        'failure_threshold': self.failure_threshold,
    })
    def _on_failure(self) -> None:
        with self._lock:
            self._stats.total_calls += 1
            self._stats.total_failures += 1
            self._stats.consecutive_failures += 1
            self._stats.consecutive_successes = 0
            self._stats.last_failure_time = time.time()

            if self._state == State.HALF_OPEN:
                # Probe failed — reopen
                self._state = State.OPEN
                self._opened_at = time.time()
            elif self._state == State.CLOSED:
                if self._stats.consecutive_failures >= self.failure_threshold:
                    self._state = State.OPEN
                    self._opened_at = time.time()

    def _should_attempt_reset(self) -> bool:
        if self._opened_at is None:
            return False
        return (time.time() - self._opened_at) >= self.recovery_timeout

    def _time_until_recovery(self) -> float:
        if self._opened_at is None:
            return 0.0
        elapsed = time.time() - self._opened_at
        return max(0.0, self.recovery_timeout - elapsed)
