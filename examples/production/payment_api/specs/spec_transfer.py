"""Transfer Spec — atomic fund transfer with conservation.

The most critical spec: proves that money is never created or destroyed
during a transfer. The sum of all accounts is invariant.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class TransferSpec(Spec):
    """Atomic transfer between two accounts with conservation law."""

    from_balance: BoundedInt[0, 10000000]
    to_balance: BoundedInt[0, 10000000]
    total_in_system: BoundedInt[0, 20000000]

    @invariant
    def conservation(self):
        """Money is neither created nor destroyed."""
        return self.from_balance + self.to_balance == self.total_in_system

    @invariant
    def non_negative(self):
        """No account goes negative."""
        return And(self.from_balance >= 0, self.to_balance >= 0)

    @transition
    def transfer(self, amount: BoundedInt[1, 1000000]):
        """Transfer funds — debit and credit atomically."""
        require(self.from_balance >= amount)
        require(self.to_balance + amount <= 10000000)
        self.from_balance -= amount
        self.to_balance += amount

    @transition
    def deposit(self, amount: BoundedInt[1, 1000000]):
        """External deposit into from_balance."""
        require(self.from_balance + amount <= 10000000)
        require(self.total_in_system + amount <= 20000000)
        self.from_balance += amount
        self.total_in_system += amount
