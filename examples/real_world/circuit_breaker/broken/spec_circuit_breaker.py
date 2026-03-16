"""Broken circuit breaker spec — trip_open missing threshold guard.

The bug: a circuit breaker that can be tripped open even when failures
haven't reached the threshold. This could happen if the failure counting
and state transition are in separate code paths with a race condition.
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenCircuitBreakerSpec(Spec):
    state: BoundedInt[0, 2]
    failure_count: BoundedInt[0, 100]
    failure_threshold: BoundedInt[1, 100]

    @invariant
    def valid_state(self):
        return And(self.state >= 0, self.state <= 2)

    @invariant
    def open_means_threshold_reached(self):
        return implies(self.state == 1, self.failure_count >= self.failure_threshold)

    @transition
    def record_failure(self):
        require(self.state == 0)
        require(self.failure_count + 1 <= 100)
        self.failure_count += 1

    @transition
    def trip_open(self):
        """BUG: Missing require(failure_count >= failure_threshold)."""
        require(self.state == 0)
        # Should have: require(self.failure_count >= self.failure_threshold)
        self.state = 1

    @transition
    def attempt_reset(self):
        require(self.state == 1)
        self.state = 2

    @transition
    def reset_success(self):
        require(self.state == 2)
        self.state = 0
        self.failure_count = 0
