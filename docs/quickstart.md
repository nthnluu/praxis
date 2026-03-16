# Get started with Praxis

Complete this guide in under 5 minutes. You install Praxis, write a spec, and run verification.

## Install Praxis

```bash
pip install praxis
```

## Write your first spec

Create `specs/spec_account.py`:

```python
from praxis import Spec, invariant, transition, require
from praxis.types import Nat, PosInt

class AccountSpec(Spec):
    balance: Nat  # non-negative integer

    @invariant
    def non_negative(self):
        return self.balance >= 0

    @transition
    def withdraw(self, amount: PosInt):
        require(self.balance >= amount)
        self.balance -= amount

    @transition
    def deposit(self, amount: PosInt):
        self.balance += amount
```

## Run verification

```bash
# Via pytest
pytest specs/spec_account.py -v

# Via CLI
praxis check specs/spec_account.py
```

## Understand the results

Praxis checks two properties:

1. **Invariant consistency** -- All `@invariant` properties are satisfiable simultaneously (they don't contradict each other).
2. **Transition preservation** -- Every `@transition` preserves all invariants for all valid inputs. If the invariants hold before the transition, they hold after.

The `withdraw` transition passes because the `require(self.balance >= amount)` guard prevents the balance from going negative. Remove that guard, and Praxis returns a concrete counterexample: `balance=0, amount=1, balance'=-1`.

## What PASSED means

- **Invariant PASSED** -- The invariants are consistent with each other and the type bounds. They can all be true at the same time.
- **Transition PASSED** -- The transition preserves all invariants for every valid input. If invariants hold before, they hold after.

The transition check is the important one. It determines whether your state changes are safe.

## Test your implementation against the spec

After you verify the spec model, use `praxis.fuzz()` to test that your real implementation follows the spec:

```python
import praxis

def test_account_follows_spec():
    account = BankAccount(initial_balance=500)

    result = praxis.fuzz(
        account,
        AccountSpec,
        state_extractor=lambda a: {'balance': a.balance},
        operations=[
            lambda a: a.deposit(random.randint(1, 100)),
            lambda a: a.withdraw(random.randint(1, 50)),
        ],
    )
    assert result.passed, result
```

`praxis.fuzz()` runs random sequences of operations on your implementation, checking the spec's invariants after each operation. If the implementation violates an invariant, you get a `FuzzResult` with the violating state and invariant name.

## Model non-numeric data

Praxis provides intent types for modeling strings, lists, maps, and other data structures by their properties (length, count, size). For example, `StringLength[1, 255]` models a string's length, and `ListLength[0, 100]` models a list's item count. For the full list, see the [Spec Language Reference](spec-language.md#intent--semantic-types).

## Next steps

- [Spec Language Reference](spec-language.md) -- All types, decorators, and operators
- [Write specs](writing-specs.md) -- Patterns and anti-patterns
- [Architecture](architecture.md) -- How the pipeline works
