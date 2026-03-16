"""E-commerce shopping cart with proper money handling.

Uses Decimal for currency to avoid floating-point errors. Supports
line items, quantity tracking, discount codes, and tax calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterator

from praxis import runtime_guard
from examples.real_world.ecommerce_cart.spec_cart import CartSpec


@dataclass(frozen=True)
class Product:
    """A product that can be added to a cart."""
    sku: str
    name: str
    price_cents: int  # Price in cents to avoid float issues

    @property
    def price(self) -> Decimal:
        return Decimal(self.price_cents) / 100

    def __post_init__(self):
        if self.price_cents < 1:
            raise ValueError(f"Price must be positive, got {self.price_cents}")


@dataclass
class LineItem:
    """A product with quantity in a cart."""
    product: Product
    quantity: int

    @property
    def subtotal_cents(self) -> int:
        return self.product.price_cents * self.quantity

    def __post_init__(self):
        if self.quantity < 1:
            raise ValueError(f"Quantity must be positive, got {self.quantity}")


@dataclass(frozen=True)
class DiscountCode:
    """A discount code with a fixed or percentage discount."""
    code: str
    amount_cents: int | None = None  # Fixed discount in cents
    percentage: Decimal | None = None  # Percentage (0-100)

    def apply(self, subtotal_cents: int) -> int:
        """Return the discount amount in cents."""
        if self.amount_cents is not None:
            return min(self.amount_cents, subtotal_cents)
        if self.percentage is not None:
            discount = Decimal(subtotal_cents) * self.percentage / 100
            return int(discount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        return 0


class CartError(Exception):
    pass


class ItemNotFoundError(CartError):
    pass


class ShoppingCart:
    """Shopping cart with line items, discounts, and tax.

    All monetary amounts are tracked in cents (integers) to avoid
    floating-point precision issues. Tax and discounts are calculated
    at checkout time.
    """

    def __init__(self, tax_rate: Decimal = Decimal("0.0")):
        if tax_rate < 0:
            raise ValueError("Tax rate cannot be negative")
        self.tax_rate = tax_rate
        self._items: dict[str, LineItem] = {}  # SKU -> LineItem
        self._discounts: list[DiscountCode] = []

    @property
    def item_count(self) -> int:
        """Total number of items (sum of quantities)."""
        return sum(item.quantity for item in self._items.values())

    @property
    def line_item_count(self) -> int:
        """Number of distinct products."""
        return len(self._items)

    @property
    def subtotal_cents(self) -> int:
        """Subtotal before discounts and tax."""
        return sum(item.subtotal_cents for item in self._items.values())

    @property
    def discount_cents(self) -> int:
        """Total discount amount."""
        subtotal = self.subtotal_cents
        total_discount = 0
        for code in self._discounts:
            total_discount += code.apply(subtotal)
        return min(total_discount, subtotal)  # Never discount more than subtotal

    @property
    def tax_cents(self) -> int:
        """Tax on (subtotal - discount)."""
        taxable = self.subtotal_cents - self.discount_cents
        tax = Decimal(taxable) * self.tax_rate
        return int(tax.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @property
    def total_cents(self) -> int:
        """Final total: subtotal - discount + tax."""
        return self.subtotal_cents - self.discount_cents + self.tax_cents

    @runtime_guard(CartSpec, state_extractor=lambda self: {
        'item_count': self.item_count,
        'total_cents': self.subtotal_cents,
        'discount_cents': self.discount_cents,
    })
    def add_item(self, product: Product, quantity: int = 1) -> None:
        """Add a product to the cart (or increase quantity if already present)."""
        if quantity < 1:
            raise CartError("Quantity must be at least 1")

        if product.sku in self._items:
            existing = self._items[product.sku]
            self._items[product.sku] = LineItem(
                product=product,
                quantity=existing.quantity + quantity,
            )
        else:
            self._items[product.sku] = LineItem(product=product, quantity=quantity)

    @runtime_guard(CartSpec, state_extractor=lambda self: {
        'item_count': self.item_count,
        'total_cents': self.subtotal_cents,
        'discount_cents': self.discount_cents,
    })
    def remove_item(self, sku: str, quantity: int | None = None) -> None:
        """Remove a product (or reduce quantity). None removes entirely."""
        if sku not in self._items:
            raise ItemNotFoundError(f"Product '{sku}' not in cart")

        if quantity is None:
            del self._items[sku]
            return

        if quantity < 1:
            raise CartError("Quantity must be at least 1")

        item = self._items[sku]
        new_qty = item.quantity - quantity
        if new_qty <= 0:
            del self._items[sku]
        else:
            self._items[sku] = LineItem(product=item.product, quantity=new_qty)

    @runtime_guard(CartSpec, state_extractor=lambda self: {
        'item_count': self.item_count,
        'total_cents': self.subtotal_cents,
        'discount_cents': self.discount_cents,
    })
    def apply_discount(self, code: DiscountCode) -> None:
        """Apply a discount code to the cart."""
        self._discounts.append(code)

    @runtime_guard(CartSpec, state_extractor=lambda self: {
        'item_count': self.item_count,
        'total_cents': self.subtotal_cents,
        'discount_cents': self.discount_cents,
    })
    def clear(self) -> None:
        """Remove all items and discounts."""
        self._items.clear()
        self._discounts.clear()

    def items(self) -> Iterator[LineItem]:
        """Iterate over line items."""
        return iter(self._items.values())
