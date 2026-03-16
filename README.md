# Praxis

Praxis is a lightweight specification checker for Python. You write short specs
declaring invariants your system must satisfy. A Z3-backed engine checks they
hold for all inputs within declared type bounds -- not just the ones you thought
to test. When an invariant doesn't hold, you get a concrete counterexample
showing exactly how it breaks.

## The problem

AI agents write code faster than humans can review it. A 500-line module
produced in 90 seconds is not something you can line-by-line audit at the
rate agents produce them. Tests help, but tests only check the cases you
enumerate.

Praxis inverts the workflow. Instead of reviewing the implementation, you
review a 20-line spec that declares what must never go wrong. The spec is
short enough for a domain expert to scrutinize in 60 seconds -- whether they
wrote it or an agent drafted it. The agent writes the implementation. Praxis
checks the spec model for consistency and verifies that transitions preserve
invariants. `praxis.fuzz()` then tests the live implementation against those
same invariants. If either layer catches a violation, you get a concrete
counterexample the agent can use to fix itself. The human's role shifts from
reading code to judging constraints.

## In a nutshell

You write a spec that declares the properties your system must satisfy.
This one says "money is never created or destroyed":

```python
from praxis import Spec, invariant, transition, require
from praxis.types import BoundedInt

class LedgerSpec(Spec):
    # State: the variables Praxis reasons about
    account_a: BoundedInt[0, 100_000]
    account_b: BoundedInt[0, 100_000]
    total_deposited: BoundedInt[0, 200_000]

    # Invariant: must hold after every operation, for all reachable states
    @invariant
    def conservation(self):
        return self.account_a + self.account_b == self.total_deposited

    # Transition: models a state change. Praxis proves it preserves all invariants.
    @transition
    def transfer(self, amount: BoundedInt[1, 10_000]):
        require(self.account_a >= amount)   # precondition: sufficient funds
        self.account_a -= amount            # debit source
        self.account_b += amount            # credit destination
```

The spec models the logic of your system, not the implementation. An agent
writes the real code however it wants:

```python
class Ledger:
    def __init__(self):
        self.account_a = 0
        self.account_b = 0
        self.total_deposited = 0

    def transfer(self, amount):
        self.account_a -= amount
        self.account_b += amount
```

Then you connect the implementation to the spec in a test, using
`praxis.fuzz()`:

```python
import praxis

def test_ledger_conservation():
    ledger = Ledger()
    ledger.total_deposited = 1000
    ledger.account_a = 1000

    result = praxis.fuzz(
        ledger,
        LedgerSpec,
        state_extractor=lambda l: {
            'account_a': l.account_a,
            'account_b': l.account_b,
            'total_deposited': l.total_deposited,
        },
        operations=[
            lambda l: l.transfer(random.randint(1, 100)),
        ],
    )
    assert result.passed, result
```

`praxis.fuzz()` runs random operations on the implementation and checks the
spec's invariants after each one. The implementation never imports `praxis` --
the connection lives in the test file.

Praxis also verifies the spec *model* statically -- it checks that each
transition preserves every invariant for all inputs within declared type
bounds. The static check and the fuzz test reinforce the same contract, but
they cover different gaps: the prover checks the spec's logic,
`praxis.fuzz()` checks that the real code actually follows it.

Run it like any test:

```
$ pytest spec_ledger.py -v
spec_ledger.py::LedgerSpec::invariant_conservation       PASSED
spec_ledger.py::LedgerSpec::transition_transfer           PASSED
```

If the transfer debits A but forgets to credit B, Praxis returns a
counterexample with the exact values that break the invariant:

```
INVARIANT VIOLATED: conservation

  Counterexample:
    account_a = 5000
    account_b = 3000
    total_deposited = 8000

  Inputs:
    amount = 1

  After transition `transfer`:
    account_a' = 4999
    account_b' = 3000
    total_deposited' = 8000
```

`account_a' + account_b' = 7999`, but `total_deposited' = 8000`. Money
vanished. The agent reads this, adds the missing `credit`, re-runs, green.

## How it works

Praxis compiles each spec to Z3 constraints through a small pipeline:
extraction (AST to IR), lowering (IR to Z3 expressions), and solving. For each
transition, it asks Z3: "does there exist a valid pre-state and input such that
executing this transition violates an invariant?" If Z3 returns `sat`, the model
is the counterexample. If `unsat`, the invariant is verified for all inputs
within the declared bounds.

This is bounded model checking of specification consistency and inductive
invariant preservation -- complete within the type bounds you declare, not
unbounded theorem proving. It checks the spec model, not the implementation
directly. `praxis.fuzz()` and `praxis.monitor()` bridge the gap by testing
and monitoring the implementation against the spec's invariants.

## Install

```bash
pip install praxis
```

Runs as a pytest plugin with no extra configuration, or standalone via `praxis check`.

## Limitations

- Verification is bounded by declared types. `BoundedInt[0, 100_000]` means
  Praxis checks that range exhaustively, not integers in general. The
  convenience types `Int`, `Nat`, and `PosInt` are sugar over `BoundedInt`
  with 64-bit bounds -- not unbounded integers.
- Specs model state transitions, not arbitrary Python. Complex control flow,
  I/O, and side effects are outside scope.
- Z3 can time out on specs with many interacting real-valued variables. Praxis
  falls back to randomized fuzzing in that case.
- `iff`, `forall`, and `exists` are available as runtime Python functions but
  are **not** supported inside `@invariant` or `@transition` methods. The
  compiler only supports `And`, `Or`, `Not`, `implies`, and `require` as
  callable functions in spec expressions.
- Each transition is verified independently. Praxis does not verify multi-step
  sequences of transitions (temporal properties).

## Documentation

- [Quickstart](docs/quickstart.md)
- [Spec Language](docs/spec-language.md)
- [Architecture](docs/architecture.md)
- [Agent Integration](docs/agent-integration.md)

## License

MIT
