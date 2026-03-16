"""Fraud Detection Spec — velocity and amount limit checks.

Proves that the fraud detector correctly enforces transaction limits
and velocity windows.
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class FraudDetectorSpec(Spec):
    """Fraud detection with per-transaction and velocity limits."""

    transaction_amount: BoundedInt[0, 10000000]
    max_transaction: BoundedInt[1, 10000000]
    window_total: BoundedInt[0, 100000000]
    velocity_limit: BoundedInt[1, 100000000]
    account_frozen: BoundedInt[0, 1]

    @invariant
    def amount_within_limit(self):
        """No approved transaction exceeds the per-txn limit."""
        return self.transaction_amount <= self.max_transaction

    @invariant
    def velocity_within_limit(self):
        """Window total never exceeds velocity limit after approval."""
        return self.window_total <= self.velocity_limit

    @invariant
    def frozen_means_zero_activity(self):
        """Frozen accounts have no new transaction amount."""
        return implies(self.account_frozen == 1, self.transaction_amount == 0)

    @transition
    def approve_transaction(self, amount: BoundedInt[1, 1000000]):
        """Approve a transaction — all checks must pass."""
        require(self.account_frozen == 0)
        require(amount <= self.max_transaction)
        require(self.window_total + amount <= self.velocity_limit)
        self.transaction_amount = amount
        self.window_total += amount

    @transition
    def reset_window(self):
        """Reset the velocity window (time-based in real implementation)."""
        self.window_total = 0
        self.transaction_amount = 0
