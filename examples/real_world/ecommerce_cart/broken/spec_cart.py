"""Broken cart spec — remove_item doesn't guard discount consistency.

Bug: remove_item reduces total_cents without checking that
total_cents - price_cents >= discount_cents. This violates the
discount_bounded invariant (discount can exceed total after removal).
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenCartSpec(Spec):
    item_count: BoundedInt[0, 1000]
    total_cents: BoundedInt[0, 10000000]
    discount_cents: BoundedInt[0, 10000000]

    @invariant
    def items_non_negative(self):
        return self.item_count >= 0

    @invariant
    def total_non_negative(self):
        return self.total_cents >= 0

    @invariant
    def discount_bounded(self):
        return self.discount_cents <= self.total_cents

    @transition
    def add_item(self, price_cents: BoundedInt[1, 100000]):
        require(self.item_count + 1 <= 1000)
        require(self.total_cents + price_cents <= 10000000)
        self.item_count += 1
        self.total_cents += price_cents

    @transition
    def remove_item(self, price_cents: BoundedInt[1, 100000]):
        """BUG: Missing guard for discount consistency."""
        require(self.item_count > 0)
        require(self.total_cents >= price_cents)
        # Missing: require(self.total_cents - price_cents >= self.discount_cents)
        self.item_count -= 1
        self.total_cents -= price_cents

    @transition
    def apply_discount(self, amount_cents: BoundedInt[1, 100000]):
        require(self.discount_cents + amount_cents <= self.total_cents)
        self.discount_cents += amount_cents
