"""Financial Ledger Spec — double-entry bookkeeping.

Proves:
- Conservation of money: total across accounts is unchanged by transfers
- No account goes below overdraft limit
- Transfer amounts are always positive
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class LedgerSpec(Spec):
    """Two-account ledger with conservation law."""

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
        """Transfer from A to B."""
        require(self.account_a >= amount)
        self.account_a -= amount
        self.account_b += amount

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
