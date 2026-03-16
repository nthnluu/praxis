# Write specs

## Start with your critical invariant

Identify the one property that must never be violated. Start there.

```python
# Weak: trivial property
@invariant
def has_name(self):
    return self.name != ""

# Better: critical safety property
@invariant
def no_overdraft(self):
    return self.balance >= 0
```

## Keep specs small

Write one spec per concern. Do not create a single spec that models your entire system.

```python
# Avoid: one spec for everything
class SystemSpec(Spec):
    balance: ...
    queue_size: ...
    cpu_usage: ...
    # 20 invariants mixing different concerns

# Prefer: separate specs for separate concerns
class AccountSpec(Spec):
    balance: BoundedInt[0, 1000000]
    ...

class QueueSpec(Spec):
    size: BoundedInt[0, 10000]
    ...
```

## Name invariants descriptively

Use domain language. The name should communicate what the invariant protects.

```python
# Unclear
@invariant
def inv1(self):
    return self.x <= self.y

# Clear
@invariant
def allocated_never_exceeds_capacity(self):
    return self.vram_used <= self.vram_total
```

## Define initial states

Use `@initial` to declare what counts as a valid starting state. Praxis checks that every initial state satisfies all invariants (the induction base case).

```python
class AccountSpec(Spec):
    balance: Nat

    @initial
    def starts_at_zero(self):
        return self.balance == 0

    @invariant
    def non_negative(self):
        return self.balance >= 0
```

## Model data structures

Praxis reasons about numbers, not strings or containers. When your system has a username, a shopping cart, or a cache, you model the property that matters -- length, count, size -- not the contents.

Intent types make this explicit:

```python
# Before: works, but the name "username_length" is noise
class UserSpec(Spec):
    username_length: BoundedInt[1, 255]

# After: intent is clear -- this field IS the username, modeled by its length
class UserSpec(Spec):
    username: StringLength[1, 255]
```

More examples:

```python
class ShoppingCartSpec(Spec):
    items: ListLength[0, 100]            # list with 0-100 items
    unique_categories: SetSize[0, 50]    # up to 50 distinct categories
    metadata: MapSize[0, 20]             # up to 20 key-value pairs
    payload: ByteSize[0, 10_000_000]     # up to 10 MB
    discount: Percentage[0, 100]         # 0-100%
```

Every intent type is sugar over `BoundedInt`. Z3 sees the same constraints either way. The difference is readability: `items: ListLength[0, 100]` says "this is a list with up to 100 items," while `item_count: BoundedInt[0, 100]` forces the reader to infer what the number represents.

Humans read the intent ("username has 1-255 characters"). Agents and verifiers read the constraints (`BoundedInt[1, 255]`). Intent types serve both audiences from the same source.

## Common patterns

### Resource bounds

```python
@invariant
def no_overcommit(self):
    return self.used <= self.capacity
```

### Conservation laws

```python
@invariant
def money_conserved(self):
    return self.account_a + self.account_b == self.total
```

### Monotonicity

```python
@invariant
def counter_never_decreases(self):
    return self.counter >= 0
```

### Conditional properties

```python
@invariant
def active_implies_configured(self):
    return implies(self.active == 1, self.config_version > 0)
```

## Anti-patterns

### Over-specifying implementation

```python
# Constrains HOW, not WHAT
@invariant
def uses_specific_algorithm(self):
    return self.internal_state == self.x * 2 + 1

# Constrains the OUTCOME
@invariant
def result_in_range(self):
    return And(self.result >= 0, self.result <= 100)
```

### Invariants that depend on transition order

```python
# Assumes a specific sequence of operations
@invariant
def initialized_before_use(self):
    return implies(self.step == 2, self.step_1_done == 1)

# State machine with clear transitions
@transition
def initialize(self):
    require(self.status == 0)
    self.status = 1
```

## Use the guard pattern

Every transition that modifies bounded state needs guards:

```python
@transition
def schedule_job(self, vram: BoundedInt[1, 80]):
    # Guard: check BEFORE mutating
    require(self.vram_used + vram <= self.vram_total)
    # Mutate: safe because of the guard
    self.vram_used += vram
```

If you omit the guard, Praxis catches it with a counterexample.

## Connect your spec to real code

After you verify a spec model, use `praxis.fuzz()` to test that your implementation follows the spec. The implementation never imports `praxis` -- the connection lives in your test file.

```python
import random
import praxis

def test_scheduler_follows_spec():
    scheduler = GPUScheduler(vram_total=80)

    result = praxis.fuzz(
        scheduler,
        GPUSchedulerSpec,
        state_extractor=lambda s: {
            'vram_total': s.vram_total,
            'vram_used': s.vram_used,
        },
        operations=[
            lambda s: s.schedule_job(random.randint(1, 40)),
            lambda s: s.release_job(random.randint(1, 20)),
        ],
    )
    assert result.passed, result
```

For production monitoring, use `praxis.monitor()` to check invariants at runtime without modifying the implementation class:

```python
import praxis

# In app startup or conftest.py
praxis.monitor(
    GPUScheduler,
    GPUSchedulerSpec,
    state_extractor=lambda self: {
        'vram_total': self.vram_total,
        'vram_used': self.vram_used,
    },
    methods=["schedule_job", "release_job"],
    mode="log",
)
```

For details on all connection modes, see the [Spec Language Reference](spec-language.md#connect-specs-to-implementations).
