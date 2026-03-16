# Financial Ledger

## The Problem

Financial ledgers are one of the oldest and most critical pieces of software in existence. Every bank, payment processor, and accounting system relies on the fundamental constraint that money is neither created nor destroyed -- it only moves between accounts. When this invariant breaks, the consequences range from mysterious off-by-one-cent reconciliation errors to catastrophic losses where funds vanish from the system entirely.

The most dangerous bugs are partial transactions. A transfer between two accounts requires two operations: debit the source and credit the destination. If the system crashes, throws an exception, or has a logic error between these two steps, money disappears. The source account was debited but the destination never received the funds. In a busy production system, this kind of bug might go unnoticed for hours or days -- the total across all accounts silently drifts away from reality, and by the time someone notices, the audit trail is a mess.

Double-entry bookkeeping was invented in 13th-century Italy precisely to catch these errors. Every transaction produces two entries that must sum to zero. If they don't, the books don't balance, and you know something went wrong. But encoding this discipline correctly in code -- especially with concurrent access, error handling, and edge cases -- is where bugs hide. A missing `+= amount` on one side of a transfer, an exception handler that commits a partial transaction, or a race condition between balance check and debit: these are the defects that unit tests routinely miss because they require testing specific interleaving of operations.

## The Implementation

`ledger.py` -- A production-style `Ledger` class using:
- **`sqlite3`** for ACID-compliant persistent storage (in-memory by default)
- **`contextlib.contextmanager`** for safe transaction scoping with automatic rollback
- **`dataclasses`** for `Entry` and `Account` data structures
- **Double-entry bookkeeping**: every transfer creates both a debit and credit entry within a single transaction

### SQLite Schema

```
accounts     (name TEXT PK, created_at REAL)
transactions (id INTEGER PK, timestamp REAL, description TEXT)
entries      (id INTEGER PK, transaction_id FK, account_name FK, amount REAL)
```

Balance is computed as `SUM(entries.amount)` for an account -- positive entries are credits, negative are debits. This append-only design makes the system auditable: you never update or delete entries, you only add new ones.

### Key Methods

```python
class Ledger:
    def create_account(self, name: str, initial_balance: float = 0.0) -> None
    def transfer(self, from_account: str, to_account: str, amount: float) -> int
    def deposit(self, account: str, amount: float) -> int
    def withdraw(self, account: str, amount: float) -> int
    def balance(self, account: str) -> float
    def get_all_balances(self) -> list[Account]
```

The `transfer` method is the critical one: it wraps the debit and credit in a single SQLite `BEGIN IMMEDIATE` / `COMMIT` transaction. If anything fails between the two `INSERT` statements, the entire transaction is rolled back -- no partial transfers.

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/ledger/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test file, not in the implementation:

```python
import praxis
from examples.real_world.ledger.ledger import Ledger
from examples.real_world.ledger.spec_ledger import LedgerSpec

def test_conservation():
    ledger = Ledger()  # in-memory SQLite
    ledger.create_account("alice", initial_balance=1000)
    ledger.create_account("bob", initial_balance=1000)

    result = praxis.fuzz(
        ledger,
        LedgerSpec,
        state_extractor=lambda l: {
            'account_a': int(l.balance('alice')),
            'account_b': int(l.balance('bob')),
            'total_deposited': int(l.balance('alice') + l.balance('bob')),
        },
        operations=[
            lambda l: l.transfer('alice', 'bob', random.randint(1, 50)),
            lambda l: l.transfer('bob', 'alice', random.randint(1, 50)),
        ],
        iterations=10000,
    )
    assert result.passed, result
```

See `test_ledger.py` for the full test suite.

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    Ledger,
    LedgerSpec,
    state_extractor=_ledger_state,
    methods=["transfer", "deposit"],
    mode="log",   # or "enforce" to raise on violation
)
```

### 4. Per-method decorators (legacy, still supported)

The `transfer` and `deposit` methods are currently decorated with `@runtime_guard`:

```python
from praxis import runtime_guard

@runtime_guard(LedgerSpec, state_extractor=_ledger_state)
def transfer(self, from_account, to_account, amount): ...
```

The `state_extractor` bridges the real SQLite-backed ledger to the spec's abstract two-account model. It reads all account balances from the database, maps the first two (alphabetically) to `account_a` and `account_b`, and computes `total_deposited` as the sum of all balances. After every `transfer` or `deposit`, the guard verifies the conservation law (`account_a + account_b == total_deposited`) and that no account goes negative.

## The Spec

`spec_ledger.py` models a simplified two-account ledger with three state variables:

- **`account_a`** and **`account_b`**: balances bounded to `[0, 100000]`
- **`total_deposited`**: tracks cumulative deposits, bounded to `[0, 200000]`

### Invariants

1. **`conservation`**: `account_a + account_b == total_deposited`. This is the fundamental law of double-entry bookkeeping -- money in the system equals money put into the system. Transfers move money between accounts but never change the total. Only deposits increase `total_deposited` and a corresponding account balance by the same amount.

2. **`non_negative_balances`**: Both `account_a >= 0` and `account_b >= 0`. No account can go negative (no overdraft facility in this model).

### Transitions

- **`transfer_a_to_b(amount)`**: Requires `account_a >= amount`, then atomically decrements A and increments B by the same amount. The total is unchanged.
- **`transfer_b_to_a(amount)`**: The reverse direction.
- **`deposit_to_a(amount)`**: Adds to both `account_a` and `total_deposited`, with upper-bound guards.

## What Praxis Proves

For **every possible** combination of account balances, deposit totals, and transfer amounts:

1. Money is conserved -- the sum of all account balances always equals total deposits
2. No account balance ever goes negative
3. Transfers never create or destroy money
4. Deposits correctly track the total money in the system
5. All upper-bound guards prevent overflow
6. Every transition preserves both invariants simultaneously

## The Bug Praxis Catches

In `broken/spec_ledger.py`, the `transfer_a_to_b` transition performs the debit but omits the credit:

```python
@transition
def transfer_a_to_b(self, amount: BoundedInt[1, 10000]):
    """BUG: Deducts from A but doesn't credit B -- money vanishes."""
    require(self.account_a >= amount)
    self.account_a -= amount
    # Missing: self.account_b += amount
```

Praxis finds this immediately:

```
INVARIANT VIOLATED: conservation

  Counterexample:
    account_a = 1
    account_b = 0
    total_deposited = 1

  After transition `transfer_a_to_b(amount=1)`:
    account_a' = 0
    account_b' = 0
    total_deposited' = 1
```

Translation: start with 1 unit in account A, 0 in account B, and 1 total deposited. Transfer 1 from A to B. Account A drops to 0, but account B stays at 0 -- the money vanished. Now `account_a + account_b = 0` but `total_deposited = 1`. The conservation law is broken.

This is exactly the class of bug that causes real financial incidents. In a production system, the equivalent would be a transfer handler that commits the debit to the database, then crashes before writing the credit. Without the ACID transaction wrapping both writes, the money is gone. The spec proves that any correct implementation **must** atomically apply both sides of the transfer.

## Run It

```bash
# Static verification
praxis check examples/real_world/ledger/
praxis check examples/real_world/ledger/broken/

# Fuzz testing (recommended)
pytest examples/real_world/ledger/test_ledger.py -v

# All tests
pytest examples/real_world/ledger/ -v
```
