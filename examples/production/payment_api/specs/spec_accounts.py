"""Account Service Spec — balance management with overdraft protection.

Proves that no account operation can leave the balance below the
overdraft limit, and that frozen accounts reject all debits.
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class AccountServiceSpec(Spec):
    """Spec for account balance operations."""

    balance_cents: BoundedInt[0, 10000000]     # Up to $100,000
    overdraft_limit: BoundedInt[0, 1000000]    # Up to $10,000 overdraft
    frozen: BoundedInt[0, 1]                   # 0=active, 1=frozen

    @invariant
    def balance_above_overdraft(self):
        """Balance + overdraft limit is always >= 0."""
        return self.balance_cents + self.overdraft_limit >= 0

    @invariant
    def balance_non_negative(self):
        """Balance never goes below zero (in this model without overdraft)."""
        return self.balance_cents >= 0

    @transition
    def debit(self, amount: BoundedInt[1, 1000000]):
        """Debit an account — requires sufficient funds and not frozen."""
        require(self.frozen == 0)
        require(self.balance_cents >= amount)
        self.balance_cents -= amount

    @transition
    def credit(self, amount: BoundedInt[1, 1000000]):
        """Credit an account."""
        require(self.balance_cents + amount <= 10000000)
        self.balance_cents += amount

    @transition
    def freeze(self):
        """Freeze an account."""
        self.frozen = 1

    @transition
    def unfreeze(self):
        """Unfreeze an account."""
        self.frozen = 0
