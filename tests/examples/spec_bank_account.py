"""Bank account specification — balance must never go negative."""

from praxis import Spec, invariant, transition
from praxis.types import BoundedInt
from praxis.decorators import require


class BankAccountSpec(Spec):
    """A simple bank account: balance >= 0."""

    balance: BoundedInt[0, 100000]

    @invariant
    def non_negative_balance(self):
        return self.balance >= 0

    @transition
    def deposit(self, amount: BoundedInt[1, 10000]):
        require(self.balance + amount <= 100000)
        self.balance += amount

    @transition
    def withdraw(self, amount: BoundedInt[1, 10000]):
        require(self.balance >= amount)
        self.balance -= amount
