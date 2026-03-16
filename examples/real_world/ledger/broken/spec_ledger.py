"""Broken ledger spec — transfer deducts but doesn't credit.

This spec is identical to the correct one except that transfer_a_to_b only
performs the debit (subtracting from account_a) without the corresponding
credit (adding to account_b). This simulates a crash or bug between the
two halves of a double-entry transaction.

The conservation invariant — account_a + account_b == total_deposited —
will be violated because money disappears from the system.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenLedgerSpec(Spec):
    """Ledger spec where transfer_a_to_b forgets to credit account_b."""

    account_a: BoundedInt[0, 100000]
    account_b: BoundedInt[0, 100000]
    total_deposited: BoundedInt[0, 200000]

    @invariant
    def conservation(self):
        """Total money across accounts equals total deposited."""
        return self.account_a + self.account_b == self.total_deposited

    @invariant
    def non_negative_balances(self):
        """No account goes negative."""
        return And(self.account_a >= 0, self.account_b >= 0)

    @transition
    def transfer_a_to_b(self, amount: BoundedInt[1, 10000]):
        """BUG: Deducts from A but doesn't credit B — money vanishes."""
        require(self.account_a >= amount)
        self.account_a -= amount
        # Missing: self.account_b += amount

    @transition
    def transfer_b_to_a(self, amount: BoundedInt[1, 10000]):
        """Transfer from B to A."""
        require(self.account_b >= amount)
        self.account_b -= amount
        self.account_a += amount

    @transition
    def deposit_to_a(self, amount: BoundedInt[1, 10000]):
        """Deposit into account A."""
        require(self.account_a + amount <= 100000)
        require(self.total_deposited + amount <= 200000)
        self.account_a += amount
        self.total_deposited += amount
