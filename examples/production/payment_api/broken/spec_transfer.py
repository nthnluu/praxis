"""Broken transfer spec — debit without credit (partial transfer).

Bug: The transfer transition deducts from from_balance but doesn't
credit to_balance. This simulates a crash between debit and credit
in a non-atomic implementation. Violates the conservation invariant.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenTransferSpec(Spec):
    from_balance: BoundedInt[0, 10000000]
    to_balance: BoundedInt[0, 10000000]
    total_in_system: BoundedInt[0, 20000000]

    @invariant
    def conservation(self):
        return self.from_balance + self.to_balance == self.total_in_system

    @invariant
    def non_negative(self):
        return And(self.from_balance >= 0, self.to_balance >= 0)

    @transition
    def transfer(self, amount: BoundedInt[1, 1000000]):
        """BUG: Debit without credit — money vanishes."""
        require(self.from_balance >= amount)
        self.from_balance -= amount
        # Missing: self.to_balance += amount
