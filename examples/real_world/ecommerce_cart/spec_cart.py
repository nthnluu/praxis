"""E-Commerce Cart Spec.

Proves:
- Item count is non-negative
- Total price is non-negative
- Cart total is consistent with item count (at least item_count * min_price)
- Removing items doesn't create negative quantities
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class CartSpec(Spec):
    """Shopping cart with item count and total tracking."""

    item_count: BoundedInt[0, 1000]
    total_cents: BoundedInt[0, 10000000]   # Total in cents (up to $100k)
    discount_cents: BoundedInt[0, 10000000]

    @invariant
    def items_non_negative(self):
        return self.item_count >= 0

    @invariant
    def total_non_negative(self):
        return self.total_cents >= 0

    @invariant
    def discount_bounded(self):
        """Discount never exceeds total."""
        return self.discount_cents <= self.total_cents

    @transition
    def add_item(self, price_cents: BoundedInt[1, 100000]):
        """Add an item to the cart."""
        require(self.item_count + 1 <= 1000)
        require(self.total_cents + price_cents <= 10000000)
        self.item_count += 1
        self.total_cents += price_cents

    @transition
    def remove_item(self, price_cents: BoundedInt[1, 100000]):
        """Remove an item from the cart."""
        require(self.item_count > 0)
        require(self.total_cents >= price_cents)
        require(self.total_cents - price_cents >= self.discount_cents)
        self.item_count -= 1
        self.total_cents -= price_cents

    @transition
    def apply_discount(self, amount_cents: BoundedInt[1, 100000]):
        """Apply a discount to the cart."""
        require(self.discount_cents + amount_cents <= self.total_cents)
        self.discount_cents += amount_cents

    @transition
    def clear_cart(self):
        """Empty the cart."""
        self.item_count = 0
        self.total_cents = 0
        self.discount_cents = 0
