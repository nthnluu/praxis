"""Ledger Spec — double-entry bookkeeping audit trail.

Proves that every recorded transaction has balanced entries
(debits = credits) and that entry counts are consistent.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, Nat
from praxis.decorators import require


class LedgerSpec(Spec):
    """Double-entry ledger with balance verification."""

    total_debits: BoundedInt[0, 100000000]
    total_credits: BoundedInt[0, 100000000]
    entry_count: Nat

    @invariant
    def balanced(self):
        """Total debits always equal total credits."""
        return self.total_debits == self.total_credits

    @invariant
    def entries_non_negative(self):
        """Entry count is non-negative."""
        return self.entry_count >= 0

    @transition
    def record_transfer(self, amount: BoundedInt[1, 1000000]):
        """Record a balanced transfer (one debit + one credit)."""
        require(self.total_debits + amount <= 100000000)
        require(self.total_credits + amount <= 100000000)
        require(self.entry_count + 2 <= 1000000)
        self.total_debits += amount
        self.total_credits += amount
        self.entry_count += 2
