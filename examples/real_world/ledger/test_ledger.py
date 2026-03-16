"""Fuzz-test the Ledger against LedgerSpec.

Demonstrates the recommended praxis.fuzz() approach for a SQLite-backed
double-entry ledger.  The spec connection lives entirely in the test;
the implementation keeps its @runtime_guard decorators for production
monitoring.
"""

import random

import praxis
from examples.real_world.ledger.ledger import Ledger
from examples.real_world.ledger.spec_ledger import LedgerSpec


ACCOUNT_A = "alice"
ACCOUNT_B = "bob"


def _make_ledger(initial_a: int = 500, initial_b: int = 500) -> Ledger:
    """Create an in-memory ledger with two funded accounts."""
    ledger = Ledger()  # in-memory SQLite
    ledger.create_account(ACCOUNT_A, initial_balance=initial_a)
    ledger.create_account(ACCOUNT_B, initial_balance=initial_b)
    return ledger


def _state(ledger: Ledger) -> dict:
    """Extract spec-compatible state from the ledger."""
    bal_a = ledger.balance(ACCOUNT_A)
    bal_b = ledger.balance(ACCOUNT_B)
    return {
        "account_a": int(bal_a),
        "account_b": int(bal_b),
        "total_deposited": int(bal_a + bal_b),
    }


class TestLedgerFuzz:
    """Fuzz the Ledger with random transfers and deposits."""

    def test_conservation_under_transfers(self):
        ledger = _make_ledger(initial_a=1000, initial_b=1000)

        result = praxis.fuzz(
            ledger,
            LedgerSpec,
            state_extractor=_state,
            operations=[
                lambda l: l.transfer(ACCOUNT_A, ACCOUNT_B, random.randint(1, 50)),
                lambda l: l.transfer(ACCOUNT_B, ACCOUNT_A, random.randint(1, 50)),
            ],
            iterations=500,
            seed=42,
        )
        assert result.passed, result

    def test_conservation_with_deposits(self):
        ledger = _make_ledger(initial_a=100, initial_b=100)

        result = praxis.fuzz(
            ledger,
            LedgerSpec,
            state_extractor=_state,
            operations=[
                lambda l: l.deposit(ACCOUNT_A, random.randint(1, 50)),
                lambda l: l.deposit(ACCOUNT_B, random.randint(1, 50)),
                lambda l: l.transfer(ACCOUNT_A, ACCOUNT_B, random.randint(1, 30)),
                lambda l: l.transfer(ACCOUNT_B, ACCOUNT_A, random.randint(1, 30)),
            ],
            iterations=500,
            seed=99,
        )
        assert result.passed, result

    def test_no_negative_balances(self):
        ledger = _make_ledger(initial_a=10, initial_b=10)

        result = praxis.fuzz(
            ledger,
            LedgerSpec,
            state_extractor=_state,
            operations=[
                lambda l: l.transfer(ACCOUNT_A, ACCOUNT_B, random.randint(1, 20)),
                lambda l: l.transfer(ACCOUNT_B, ACCOUNT_A, random.randint(1, 20)),
                lambda l: l.withdraw(ACCOUNT_A, random.randint(1, 15)),
                lambda l: l.withdraw(ACCOUNT_B, random.randint(1, 15)),
            ],
            iterations=500,
            seed=7,
        )
        assert result.passed, result
