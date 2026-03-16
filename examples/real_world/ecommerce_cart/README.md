# E-Commerce Cart

## The Problem

Shopping carts seem simple — add items, remove items, calculate a total. But money handling is where the subtlety hides. Using floating-point for currency creates rounding errors that compound across thousands of transactions. Discount codes interact with item removal in unexpected ways: apply a $20 discount, then remove the only $15 item, and the discount now exceeds the cart total. The result is a negative "amount due" that the payment processor rejects — or worse, interprets as a refund.

These bugs are hard to catch because they require specific sequences: add items, apply discount, remove items in a particular order. Unit tests check the happy path. The edge case where discount > total after removal only appears when a QA engineer (or a customer) tries exactly the wrong combination.

## The Implementation

`cart.py` — A production-style `ShoppingCart` using:
- **`decimal.Decimal`** for all money calculations (never floats for currency)
- **`dataclasses`** for `Product`, `LineItem`, and `DiscountCode`
- Integer cents for internal tracking to avoid precision issues

Key methods:
```python
class ShoppingCart:
    def add_item(self, product: Product, quantity: int) -> None
    def remove_item(self, sku: str, quantity: int | None) -> None
    def apply_discount(self, code: DiscountCode) -> None
    def clear(self) -> None
    # Properties: item_count, subtotal_cents, discount_cents, tax_cents, total_cents
```

Discounts support both fixed amounts and percentages, capped at the subtotal to prevent negative totals.

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/ecommerce_cart/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    cart,
    CartSpec,
    state_extractor=lambda self: {
        'item_count': self.item_count,
        'total_cents': self.subtotal_cents,
        'discount_cents': self.discount_cents,
    },
    operations=[
        lambda c: c.add_item(some_product, quantity=1),
        lambda c: c.remove_item("SKU-1"),
        lambda c: c.apply_discount(discount_code),
    ],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    ShoppingCart,
    CartSpec,
    state_extractor=lambda self: {
        'item_count': self.item_count,
        'total_cents': self.subtotal_cents,
        'discount_cents': self.discount_cents,
    },
    methods=["add_item", "remove_item", "apply_discount", "clear"],
    mode="log",
)
```

### 4. Per-method decorators (legacy, still supported)

Every mutating method is currently decorated with `@runtime_guard`:

```python
@runtime_guard(CartSpec, state_extractor=lambda self: {
    'item_count': self.item_count,
    'total_cents': self.subtotal_cents,
    'discount_cents': self.discount_cents,
})
def add_item(self, product: Product, quantity: int = 1) -> None: ...
```

The `state_extractor` maps the real `ShoppingCart` properties to the abstract spec variables. After every call, the guard verifies that item count is non-negative, total is non-negative, and discount never exceeds the total. If any invariant is violated, an `AssertionError` is raised immediately.

## The Spec

`spec_cart.py` tracks three values:

1. **`items_non_negative`**: Item count never goes below zero
2. **`total_non_negative`**: Total price never goes negative
3. **`discount_bounded`**: `discount_cents <= total_cents` — discounts never exceed the cart total

The critical transition is `remove_item`, which must check `total_cents - price_cents >= discount_cents` before reducing the total.

## What Praxis Proves

1. The cart total is always non-negative, regardless of add/remove sequence
2. Discounts never exceed the cart total, even after items are removed
3. Item count never goes negative

## The Bug Praxis Catches

In `broken/spec_cart.py`, `remove_item` doesn't check discount consistency:

```python
@transition
def remove_item(self, price_cents: BoundedInt[1, 100000]):
    require(self.item_count > 0)
    require(self.total_cents >= price_cents)
    # Missing: require(self.total_cents - price_cents >= self.discount_cents)
    self.item_count -= 1
    self.total_cents -= price_cents
```

Praxis finds: cart with `total_cents=100, discount_cents=80`, removing an item worth 50 leaves `total_cents=50` but `discount_cents=80` — discount exceeds total.

## Run It

```bash
pytest examples/real_world/ecommerce_cart/ -v
praxis check examples/real_world/ecommerce_cart/
praxis check examples/real_world/ecommerce_cart/broken/
```
