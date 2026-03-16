# Spec language reference

## Types

### Core types

| Type | Description | Example |
|------|-------------|---------|
| `Int` | Any integer | `count: Int` |
| `Nat` | Non-negative integer (>= 0) | `balance: Nat` |
| `PosInt` | Positive integer (>= 1) | `amount: PosInt` |
| `BoundedInt[lo, hi]` | Integer in [lo, hi] | `age: BoundedInt[0, 150]` |
| `BoundedFloat[lo, hi]` | Real number in [lo, hi] | `rate: BoundedFloat[0.0, 1.0]` |
| `Bool` | Boolean | `active: Bool` |

### Intent / semantic types

These types model properties of data structures (length, count, size) rather than the data itself. They are sugar over `BoundedInt` but communicate developer intent and make specs readable by both humans and agents.

| Type | Models | Example |
|------|--------|---------|
| `StringLength[min, max]` | Length of a string | `username: StringLength[1, 255]` |
| `NonEmptyString` | String with length >= 1 | `name: NonEmptyString` |
| `ListLength[min, max]` | Item count in a list/array | `cart_items: ListLength[0, 100]` |
| `MapSize[min, max]` | Entry count in a dict/map | `cache_entries: MapSize[0, 10000]` |
| `SetSize[min, max]` | Element count in a set | `unique_users: SetSize[0, 1000000]` |
| `ByteSize[min, max]` | Size in bytes | `payload: ByteSize[0, 10_000_000]` |
| `Percentage[min, max]` | Percentage value | `cpu_usage: Percentage[0, 100]` |

### Enum types

| Type | Description | Example |
|------|-------------|---------|
| `PraxisEnum` | Base class for named-state enums | See below |

Use `PraxisEnum` for state machines with named states:

```python
from praxis.types import PraxisEnum

class OrderStatus(PraxisEnum):
    PENDING = 0
    CONFIRMED = 1
    SHIPPED = 2
    DELIVERED = 3

class OrderSpec(Spec):
    status: OrderStatus
```

Enum values map to Z3 integers with membership constraints. Z3 considers only valid enum values.

### Choose the right type

- **Unconstrained integers**: Use `Int`. Use `Nat` when the value cannot be negative, `PosInt` when it must be at least 1.
- **Domain-bounded integers**: Use `BoundedInt[lo, hi]` when the domain has natural limits (VRAM capacity, port numbers).
- **Reals / decimals**: Use `BoundedFloat[lo, hi]`.
- **Strings, lists, maps, sets**: Use intent types (`StringLength`, `ListLength`, `MapSize`, `SetSize`). You model the property Praxis reasons about (length or count), not the contents. For more information, see [Model data structures](writing-specs.md#model-data-structures).
- **Byte sizes and percentages**: Use `ByteSize` and `Percentage` for self-documenting specs.
- **Named states**: Subclass `PraxisEnum`.

Prefer the most specific type that fits. `StringLength[1, 255]` communicates more than `BoundedInt[1, 255]`.

```python
from praxis.types import (
    Int, Nat, PosInt, BoundedInt, BoundedFloat, Bool,
    PraxisEnum, StringLength, NonEmptyString,
    ListLength, MapSize, SetSize, ByteSize, Percentage,
)

class MySpec(Spec):
    balance: Nat                          # >= 0
    count: Int                            # any integer
    quantity: PosInt                      # >= 1
    vram_used: BoundedInt[0, 640]        # domain-specific bounds
    temperature: BoundedFloat[0.0, 100.0]
    active: Bool
    username: StringLength[1, 64]        # string length 1-64
    cart_items: ListLength[0, 100]       # list with 0-100 items
    cpu_usage: Percentage[0, 100]        # 0-100%
```

## Decorators

### `@invariant`

Defines a property that must always hold. The method must return a boolean expression.

```python
@invariant
def non_negative(self):
    return self.balance >= 0
```

With a custom error message:

```python
@invariant(message="CRITICAL: VRAM overcommit would crash GPU kernel")
def no_overcommit(self):
    return self.vram_used <= self.vram_total
```

### `@transition`

Defines a valid state change. Parameters require Praxis type annotations. Zero-parameter transitions are supported.

```python
@transition
def deposit(self, amount: PosInt):
    require(self.balance + amount <= 1000000)
    self.balance += amount

@transition
def reset(self):
    self.balance = 0
```

### `@initial`

Defines a predicate over valid initial states. Use `@initial` to constrain what counts as a valid starting state for your spec. During verification, Praxis checks that every initial state satisfies all invariants (the induction base case).

```python
@initial
def starts_empty(self):
    return self.balance == 0
```

You can define multiple `@initial` methods. All must hold simultaneously for a state to qualify as initial.

### `@verify(target="path.to.func")`

Marks a method for verifying a real implementation function.

### `require(expr)`

Asserts a precondition. During verification, this becomes a Z3 assumption.

## Connect specs to implementations

After you verify a spec model, connect it to your real code. Praxis provides three connection modes. The implementation never imports `praxis` -- the connection lives in tests or config.

### `praxis.fuzz()` -- test-time checking

Run in tests. Fuzz-tests your implementation against the spec by running random sequences of operations and checking invariants after each one.

```python
import praxis

def test_account_invariants():
    account = BankAccount(initial_balance=500)

    result = praxis.fuzz(
        account,
        AccountSpec,
        state_extractor=lambda a: {'balance': a.balance},
        operations=[
            lambda a: a.deposit(random.randint(1, 100)),
            lambda a: a.withdraw(random.randint(1, 50)),
        ],
        iterations=10000,
    )
    assert result.passed, result
```

### `praxis.monitor()` -- runtime checking

Attach at startup or in `conftest.py`. Wraps methods on a class to check spec invariants after each call, without modifying the class itself.

```python
import praxis

# In app startup or conftest.py
praxis.monitor(
    BankAccount,
    AccountSpec,
    state_extractor=lambda self: {'balance': self.balance},
    methods=["deposit", "withdraw"],
    mode="log",       # "log" (default), "enforce", or "off"
)
```

- `mode="log"` -- logs violations without raising.
- `mode="enforce"` -- raises `AssertionError` on violation.
- `mode="off"` -- disables monitoring (no-op).

### `@runtime_guard` -- per-method decorator

Decorates individual methods. More coupled than `fuzz()` or `monitor()` because the implementation must reference the decorator.

```python
from praxis import runtime_guard

class BankAccount:
    @runtime_guard(AccountSpec, state_extractor=lambda self: {
        'balance': self.balance,
    })
    def withdraw(self, amount):
        self.balance -= amount
```

For new code, prefer `praxis.fuzz()` (in tests) or `praxis.monitor()` (at runtime). Both keep the implementation decoupled from the spec.

## Logic operators

### Supported in spec methods (compiled to Z3)

```python
from praxis import And, Or, Not, implies

And(a, b, c)           # Logical AND (variadic)
Or(a, b, c)            # Logical OR (variadic)
Not(a)                 # Logical NOT
implies(a, b)          # a -> b (if a then b)
```

### Runtime-only (NOT compiled to Z3)

These work as Python functions for runtime guards and fuzz testing, but cannot be used inside `@invariant` or `@transition` methods:

```python
from praxis import iff, forall, exists

iff(a, b)              # a <-> b (a if and only if b)
forall(range(n), pred) # Universal quantification
exists(range(n), pred) # Existential quantification
```

## Supported expressions

- Arithmetic: `+`, `-`, `*`, `//`, `%`
- Comparisons: `<`, `<=`, `>`, `>=`, `==`, `!=`
- Boolean: `and`, `or`, `not`, `And()`, `Or()`, `Not()`
- Ternary: `x if cond else y`
- State access: `self.field`
- Mutations: `self.field += expr`, `self.field = expr`
- Chained comparisons: `0 <= self.x <= 100`

## Unsupported constructs

The following raise clear errors at compile time:

- Loops (`for`, `while`)
- Function calls (except `require`, `And`, `Or`, `Not`, `implies`)
- `iff`, `forall`, `exists` (available as runtime Python functions, but not compiled to Z3 in specs)
- String/container operations
- I/O, imports

## Compose specs

Specs can inherit from other specs:

```python
class ResourceSpec(Spec):
    capacity: Nat
    used: Nat

    @invariant
    def no_overcommit(self):
        return self.used <= self.capacity

class GPUSpec(ResourceSpec):
    temperature: BoundedInt[0, 100]

    @invariant
    def thermal_limit(self):
        return self.temperature <= 85
```

`GPUSpec` verifies both `no_overcommit` and `thermal_limit`. Child specs inherit parent fields, invariants, and transitions.
