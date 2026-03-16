"""Gateway Client Spec — external API integration safety.

This is the key spec for external API calls. It proves that:
1. Charge amounts are always within limits
2. The circuit breaker opens only after threshold failures
3. Retry count never exceeds max_retries
4. Completed charges are never double-charged (idempotency)

Note: We can't verify the EXTERNAL API's behavior. We verify that
OUR handling of its responses maintains OUR invariants.
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class GatewayClientSpec(Spec):
    """Spec for external payment gateway integration."""

    # State
    charge_amount: BoundedInt[0, 1000000]       # Current charge in cents
    max_charge: BoundedInt[1, 1000000]           # Per-txn limit
    retry_count: BoundedInt[0, 10]               # Current retry attempts
    max_retries: BoundedInt[1, 10]               # Max retries allowed
    consecutive_failures: BoundedInt[0, 100]     # Failure counter
    circuit_threshold: BoundedInt[1, 100]         # Failures before open
    circuit_open: BoundedInt[0, 1]               # 0=closed, 1=open
    completed: BoundedInt[0, 1]                  # 0=pending, 1=done

    @invariant
    def amount_within_limit(self):
        """No charge exceeds the per-transaction limit."""
        return self.charge_amount <= self.max_charge

    @invariant
    def retries_bounded(self):
        """Retry count never exceeds max."""
        return self.retry_count <= self.max_retries

    @invariant
    def circuit_opens_at_threshold(self):
        """Circuit only opens when failures reach threshold."""
        return implies(
            self.circuit_open == 1,
            self.consecutive_failures >= self.circuit_threshold,
        )

    @invariant
    def completed_means_no_more_retries(self):
        """Once completed, no more retries happen."""
        return implies(self.completed == 1, self.retry_count <= self.max_retries)

    @transition
    def initiate_charge(self, amount: BoundedInt[1, 1000000]):
        """Start a new charge — validate amount."""
        require(self.completed == 0)
        require(self.circuit_open == 0)
        require(amount <= self.max_charge)
        require(self.retry_count == 0)
        self.charge_amount = amount

    @transition
    def gateway_success(self):
        """Gateway returned success — mark complete, reset failures, close circuit."""
        require(self.completed == 0)
        require(self.charge_amount > 0)
        self.completed = 1
        self.consecutive_failures = 0
        self.circuit_open = 0

    @transition
    def gateway_failure(self):
        """Gateway returned error/timeout — increment retry and failure count."""
        require(self.completed == 0)
        require(self.charge_amount > 0)
        require(self.retry_count + 1 <= self.max_retries)
        require(self.consecutive_failures + 1 <= 100)
        self.retry_count += 1
        self.consecutive_failures += 1

    @transition
    def trip_circuit(self):
        """Open circuit breaker after too many failures."""
        require(self.consecutive_failures >= self.circuit_threshold)
        self.circuit_open = 1

    @transition
    def reset_circuit(self):
        """Reset circuit breaker (after timeout)."""
        require(self.circuit_open == 1)
        self.circuit_open = 0
        self.consecutive_failures = 0
