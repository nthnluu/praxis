"""Circuit Breaker Spec — resilience pattern for service calls.

States: 0=CLOSED (normal), 1=OPEN (failing), 2=HALF_OPEN (testing recovery).

Proves:
- State is always one of the three valid values
- Failure count is non-negative and bounded
- Transitions follow the state machine rules
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class CircuitBreakerSpec(Spec):
    """Circuit breaker with closed/open/half-open states."""

    state: BoundedInt[0, 2]           # 0=closed, 1=open, 2=half_open
    failure_count: BoundedInt[0, 100]
    failure_threshold: BoundedInt[1, 100]

    @invariant
    def valid_state(self):
        return And(self.state >= 0, self.state <= 2)

    @invariant
    def failure_non_negative(self):
        return self.failure_count >= 0

    @invariant
    def open_means_threshold_reached(self):
        """If open, failures must have reached threshold."""
        return implies(self.state == 1, self.failure_count >= self.failure_threshold)

    @transition
    def record_failure(self):
        """Record a failure in closed state."""
        require(self.state == 0)
        require(self.failure_count + 1 <= 100)
        self.failure_count += 1

    @transition
    def trip_open(self):
        """Trip the breaker open when failures reach threshold."""
        require(self.state == 0)
        require(self.failure_count >= self.failure_threshold)
        self.state = 1

    @transition
    def attempt_reset(self):
        """Move from open to half-open to test recovery."""
        require(self.state == 1)
        self.state = 2

    @transition
    def reset_success(self):
        """Successful test in half-open — close the breaker."""
        require(self.state == 2)
        self.state = 0
        self.failure_count = 0

    @transition
    def reset_failure(self):
        """Failed test in half-open — reopen."""
        require(self.state == 2)
        require(self.failure_count >= self.failure_threshold)
        self.state = 1
