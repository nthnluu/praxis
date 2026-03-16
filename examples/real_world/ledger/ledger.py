"""Double-entry bookkeeping ledger backed by SQLite.

Every transaction creates both a debit and credit entry. Transfers are atomic
via SQLite ACID transactions. Backed by in-memory or file-based SQLite.
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from praxis import runtime_guard
from examples.real_world.ledger.spec_ledger import LedgerSpec


def _ledger_state(self):
    """Extract spec-compatible state from a Ledger instance.

    Maps the real SQLite-backed ledger to the two-account model in
    LedgerSpec.  Uses the first two accounts (alphabetically) as
    account_a and account_b.  total_deposited is the sum of all
    account balances, which must equal cumulative deposits if money
    is conserved.
    """
    try:
        balances = self.get_all_balances()
    except Exception:
        return {'account_a': 0, 'account_b': 0, 'total_deposited': 0}
    bal_map = {a.name: int(a.balance) for a in balances}
    names = sorted(bal_map.keys())
    account_a = bal_map[names[0]] if len(names) > 0 else 0
    account_b = bal_map[names[1]] if len(names) > 1 else 0
    total_deposited = sum(bal_map.values())
    return {
        'account_a': account_a,
        'account_b': account_b,
        'total_deposited': total_deposited,
    }


class LedgerError(Exception):
    """Base error for ledger operations."""


class AccountNotFoundError(LedgerError):
    """Raised when an account does not exist."""


class InsufficientFundsError(LedgerError):
    """Raised when a withdrawal or transfer exceeds available balance."""


class InvalidAmountError(LedgerError):
    """Raised when an amount is zero or negative."""


@dataclass(frozen=True)
class Account:
    """Summary view of an account."""
    name: str
    balance: float


class Ledger:
    """Double-entry bookkeeping ledger backed by SQLite.

    Ledger()             — in-memory database
    Ledger("path.db")    — persistent file-based database
    """

    def __init__(self, db_path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(db_path, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    def _create_schema(self) -> None:
        """Initialize the database schema."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS accounts (
                name TEXT PRIMARY KEY, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL, description TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id INTEGER NOT NULL REFERENCES transactions(id),
                account_name TEXT NOT NULL REFERENCES accounts(name),
                amount REAL NOT NULL);
        """)

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        """Context manager for an ACID transaction."""
        cursor = self._conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        try:
            yield cursor
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def create_account(self, name: str, initial_balance: float = 0.0) -> None:
        """Create a new account, optionally with an initial balance."""
        if initial_balance < 0:
            raise InvalidAmountError("Initial balance cannot be negative")

        with self._transaction() as cur:
            if cur.execute("SELECT 1 FROM accounts WHERE name = ?", (name,)).fetchone():
                raise LedgerError(f"Account '{name}' already exists")

            now = time.time()
            cur.execute("INSERT INTO accounts (name, created_at) VALUES (?, ?)", (name, now))
            if initial_balance > 0:
                cur.execute(
                    "INSERT INTO transactions (timestamp, description) VALUES (?, ?)",
                    (now, f"Initial deposit to {name}"))
                cur.execute(
                    "INSERT INTO entries (transaction_id, account_name, amount) "
                    "VALUES (?, ?, ?)", (cur.lastrowid, name, initial_balance))

    @runtime_guard(LedgerSpec, state_extractor=_ledger_state)
    def transfer(self, from_account: str, to_account: str, amount: float) -> int:
        """Atomically transfer money between accounts (double-entry)."""
        if amount <= 0:
            raise InvalidAmountError("Transfer amount must be positive")
        if from_account == to_account:
            raise LedgerError("Cannot transfer to the same account")

        with self._transaction() as cur:
            self._assert_account_exists(cur, from_account)
            self._assert_account_exists(cur, to_account)

            bal = self._compute_balance(cur, from_account)
            if bal < amount:
                raise InsufficientFundsError(
                    f"Account '{from_account}' has {bal:.2f}, need {amount:.2f}")

            now = time.time()
            cur.execute(
                "INSERT INTO transactions (timestamp, description) VALUES (?, ?)",
                (now, f"Transfer {amount:.2f}: {from_account} -> {to_account}"))
            txn_id = cur.lastrowid
            # Double-entry: debit source, credit destination
            cur.execute(
                "INSERT INTO entries (transaction_id, account_name, amount) "
                "VALUES (?, ?, ?)", (txn_id, from_account, -amount))
            cur.execute(
                "INSERT INTO entries (transaction_id, account_name, amount) "
                "VALUES (?, ?, ?)", (txn_id, to_account, amount))
            return txn_id  # type: ignore[return-value]

    @runtime_guard(LedgerSpec, state_extractor=_ledger_state)
    def deposit(self, account: str, amount: float) -> int:
        """Deposit money into an account."""
        if amount <= 0:
            raise InvalidAmountError("Deposit amount must be positive")

        with self._transaction() as cur:
            self._assert_account_exists(cur, account)
            now = time.time()
            cur.execute(
                "INSERT INTO transactions (timestamp, description) VALUES (?, ?)",
                (now, f"Deposit {amount:.2f} to {account}"))
            cur.execute(
                "INSERT INTO entries (transaction_id, account_name, amount) "
                "VALUES (?, ?, ?)", (cur.lastrowid, account, amount))
            return cur.lastrowid  # type: ignore[return-value]

    def withdraw(self, account: str, amount: float) -> int:
        """Withdraw money from an account."""
        if amount <= 0:
            raise InvalidAmountError("Withdrawal amount must be positive")
        with self._transaction() as cur:
            self._assert_account_exists(cur, account)
            current = self._compute_balance(cur, account)
            if current < amount:
                raise InsufficientFundsError(
                    f"Account '{account}' has {current:.2f}, need {amount:.2f}")
            now = time.time()
            cur.execute(
                "INSERT INTO transactions (timestamp, description) VALUES (?, ?)",
                (now, f"Withdraw {amount:.2f} from {account}"))
            cur.execute(
                "INSERT INTO entries (transaction_id, account_name, amount) "
                "VALUES (?, ?, ?)", (cur.lastrowid, account, -amount))
            return cur.lastrowid  # type: ignore[return-value]

    def balance(self, account: str) -> float:
        """Get the current balance of an account."""
        with self._transaction() as cur:
            self._assert_account_exists(cur, account)
            return self._compute_balance(cur, account)

    def get_all_balances(self) -> list[Account]:
        """Get balances for all accounts, sorted by name."""
        with self._transaction() as cur:
            rows = cur.execute(
                "SELECT a.name, COALESCE(SUM(e.amount), 0.0) FROM accounts a "
                "LEFT JOIN entries e ON e.account_name = a.name "
                "GROUP BY a.name ORDER BY a.name").fetchall()
            return [Account(name=r[0], balance=r[1]) for r in rows]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # -- Internal helpers --

    def _assert_account_exists(self, cur: sqlite3.Cursor, name: str) -> None:
        if not cur.execute("SELECT 1 FROM accounts WHERE name = ?", (name,)).fetchone():
            raise AccountNotFoundError(f"Account '{name}' does not exist")

    def _compute_balance(self, cur: sqlite3.Cursor, account: str) -> float:
        row = cur.execute(
            "SELECT COALESCE(SUM(amount), 0.0) FROM entries "
            "WHERE account_name = ?", (account,)).fetchone()
        return row[0]  # type: ignore[index]
