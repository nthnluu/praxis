"""Payment Processing API — a production-scale Flask application.

This is a complete payment API with:
- Account management with balance tracking
- Rate-limited API endpoints per merchant
- Atomic fund transfers with idempotency keys
- Fraud detection with velocity and amount limits
- Double-entry ledger for audit compliance

Run: python -m flask --app examples.production.payment_api.app run
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum, auto
from threading import Lock
from typing import Any, Generator

logger = logging.getLogger(__name__)


# ============================================================
# Domain Models
# ============================================================

class TransactionStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    REVERSED = "reversed"


@dataclass
class Account:
    id: str
    merchant_id: str
    balance_cents: int
    currency: str = "USD"
    overdraft_limit_cents: int = 0
    frozen: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass
class Transaction:
    id: str
    idempotency_key: str
    from_account: str
    to_account: str
    amount_cents: int
    currency: str
    status: TransactionStatus
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    failure_reason: str | None = None


@dataclass
class LedgerEntry:
    id: str
    transaction_id: str
    account_id: str
    amount_cents: int  # positive = credit, negative = debit
    balance_after_cents: int
    created_at: float = field(default_factory=time.time)


@dataclass
class FraudCheckResult:
    approved: bool
    reason: str | None = None
    risk_score: float = 0.0


# ============================================================
# Exceptions
# ============================================================

class PaymentError(Exception):
    """Base payment error."""
    pass

class InsufficientFundsError(PaymentError):
    pass

class AccountFrozenError(PaymentError):
    pass

class RateLimitExceededError(PaymentError):
    pass

class FraudDetectedError(PaymentError):
    pass

class DuplicateTransactionError(PaymentError):
    pass

class AccountNotFoundError(PaymentError):
    pass


# ============================================================
# Account Service
# ============================================================

class AccountService:
    """Manages account balances with overdraft protection.

    Invariants enforced:
    - Balance + overdraft_limit >= 0 (no overdraft beyond limit)
    - Frozen accounts reject all debits
    - Balance changes are atomic
    """

    def __init__(self):
        self._accounts: dict[str, Account] = {}
        self._lock = Lock()

    def create_account(
        self, merchant_id: str, initial_balance_cents: int = 0,
        currency: str = "USD", overdraft_limit_cents: int = 0,
    ) -> Account:
        """Create a new account with optional initial balance."""
        if initial_balance_cents < 0:
            raise PaymentError("Initial balance cannot be negative")
        if overdraft_limit_cents < 0:
            raise PaymentError("Overdraft limit cannot be negative")

        account = Account(
            id=uuid.uuid4().hex[:16],
            merchant_id=merchant_id,
            balance_cents=initial_balance_cents,
            currency=currency,
            overdraft_limit_cents=overdraft_limit_cents,
        )
        with self._lock:
            self._accounts[account.id] = account
        return account

    def get_account(self, account_id: str) -> Account:
        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(f"Account {account_id} not found")
        return account

    def debit(self, account_id: str, amount_cents: int) -> int:
        """Debit an account. Returns new balance. Thread-safe."""
        if amount_cents <= 0:
            raise PaymentError("Debit amount must be positive")

        with self._lock:
            account = self.get_account(account_id)
            if account.frozen:
                raise AccountFrozenError(f"Account {account_id} is frozen")

            new_balance = account.balance_cents - amount_cents
            if new_balance + account.overdraft_limit_cents < 0:
                raise InsufficientFundsError(
                    f"Insufficient funds: balance={account.balance_cents}, "
                    f"debit={amount_cents}, overdraft_limit={account.overdraft_limit_cents}"
                )
            account.balance_cents = new_balance
            return new_balance

    def credit(self, account_id: str, amount_cents: int) -> int:
        """Credit an account. Returns new balance. Thread-safe."""
        if amount_cents <= 0:
            raise PaymentError("Credit amount must be positive")

        with self._lock:
            account = self.get_account(account_id)
            account.balance_cents += amount_cents
            return account.balance_cents

    def freeze_account(self, account_id: str) -> None:
        with self._lock:
            self.get_account(account_id).frozen = True

    def unfreeze_account(self, account_id: str) -> None:
        with self._lock:
            self.get_account(account_id).frozen = False


# ============================================================
# Rate Limiter
# ============================================================

class TokenBucketRateLimiter:
    """Per-merchant API rate limiter using token bucket algorithm.

    Invariants enforced:
    - Tokens never go negative
    - Tokens never exceed bucket capacity
    - Refill is capped at capacity
    """

    def __init__(self, capacity: int = 100, refill_rate: float = 10.0):
        """
        Args:
            capacity: Maximum tokens per bucket.
            refill_rate: Tokens added per second.
        """
        if capacity < 1:
            raise ValueError("Capacity must be at least 1")
        if refill_rate <= 0:
            raise ValueError("Refill rate must be positive")

        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: dict[str, tuple[float, float]] = {}  # merchant_id -> (tokens, last_refill_time)
        self._lock = Lock()

    def allow_request(self, merchant_id: str, cost: int = 1) -> bool:
        """Check if a request is allowed and consume tokens."""
        with self._lock:
            tokens, last_refill = self._get_bucket(merchant_id)

            # Refill based on time elapsed
            now = time.time()
            elapsed = now - last_refill
            tokens = min(self.capacity, tokens + elapsed * self.refill_rate)

            if tokens >= cost:
                tokens -= cost
                self._buckets[merchant_id] = (tokens, now)
                return True
            else:
                self._buckets[merchant_id] = (tokens, now)
                return False

    def get_remaining(self, merchant_id: str) -> int:
        """Get approximate remaining tokens for a merchant."""
        with self._lock:
            tokens, last_refill = self._get_bucket(merchant_id)
            elapsed = time.time() - last_refill
            return int(min(self.capacity, tokens + elapsed * self.refill_rate))

    def _get_bucket(self, merchant_id: str) -> tuple[float, float]:
        if merchant_id not in self._buckets:
            self._buckets[merchant_id] = (float(self.capacity), time.time())
        return self._buckets[merchant_id]


# ============================================================
# Fraud Detector
# ============================================================

class FraudDetector:
    """Velocity-based fraud detection.

    Invariants enforced:
    - Single transaction amount never exceeds per-txn limit
    - Total volume in a time window never exceeds velocity limit
    - Frozen accounts are always rejected
    """

    def __init__(
        self,
        max_transaction_cents: int = 1_000_000,  # $10,000
        velocity_window_seconds: float = 3600.0,  # 1 hour
        velocity_limit_cents: int = 5_000_000,  # $50,000/hour
    ):
        self.max_transaction_cents = max_transaction_cents
        self.velocity_window = velocity_window_seconds
        self.velocity_limit_cents = velocity_limit_cents
        self._history: dict[str, list[tuple[float, int]]] = {}  # account_id -> [(time, amount)]
        self._lock = Lock()

    def check_transaction(
        self, from_account: Account, amount_cents: int,
    ) -> FraudCheckResult:
        """Run fraud checks on a proposed transaction."""
        # Check: account not frozen
        if from_account.frozen:
            return FraudCheckResult(
                approved=False, reason="Account is frozen",
                risk_score=1.0,
            )

        # Check: single transaction limit
        if amount_cents > self.max_transaction_cents:
            return FraudCheckResult(
                approved=False,
                reason=f"Amount {amount_cents} exceeds limit {self.max_transaction_cents}",
                risk_score=0.9,
            )

        # Check: velocity (total amount in time window)
        with self._lock:
            now = time.time()
            history = self._history.get(from_account.id, [])
            # Prune old entries
            cutoff = now - self.velocity_window
            history = [(t, a) for t, a in history if t > cutoff]

            window_total = sum(a for _, a in history)
            if window_total + amount_cents > self.velocity_limit_cents:
                self._history[from_account.id] = history
                return FraudCheckResult(
                    approved=False,
                    reason=f"Velocity limit exceeded: {window_total + amount_cents} > {self.velocity_limit_cents}",
                    risk_score=0.8,
                )

            # Record this transaction
            history.append((now, amount_cents))
            self._history[from_account.id] = history

        return FraudCheckResult(approved=True, risk_score=0.1)


# ============================================================
# Ledger (Audit Trail)
# ============================================================

class AuditLedger:
    """Double-entry bookkeeping ledger backed by SQLite.

    Invariants enforced:
    - Every transaction creates exactly one debit and one credit entry
    - Debit + credit for each transaction sum to zero (conservation)
    - Entries are append-only (no mutations)
    """

    def __init__(self, db_path: str = ":memory:"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS ledger_entries (
                    id TEXT PRIMARY KEY,
                    transaction_id TEXT NOT NULL,
                    account_id TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL,
                    balance_after_cents INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_ledger_txn
                    ON ledger_entries(transaction_id);
                CREATE INDEX IF NOT EXISTS idx_ledger_account
                    ON ledger_entries(account_id);
            """)

    def record_transfer(
        self, transaction_id: str,
        from_account_id: str, from_balance_after: int,
        to_account_id: str, to_balance_after: int,
        amount_cents: int,
    ) -> None:
        """Record a double-entry transfer. Atomic."""
        now = time.time()
        with self._lock:
            with self._conn:
                # Debit entry (negative)
                self._conn.execute(
                    "INSERT INTO ledger_entries VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex[:16], transaction_id,
                     from_account_id, -amount_cents, from_balance_after, now),
                )
                # Credit entry (positive)
                self._conn.execute(
                    "INSERT INTO ledger_entries VALUES (?, ?, ?, ?, ?, ?)",
                    (uuid.uuid4().hex[:16], transaction_id,
                     to_account_id, amount_cents, to_balance_after, now),
                )

    def get_entries_for_transaction(self, transaction_id: str) -> list[dict]:
        """Get all ledger entries for a transaction."""
        cursor = self._conn.execute(
            "SELECT * FROM ledger_entries WHERE transaction_id = ? ORDER BY created_at",
            (transaction_id,),
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def verify_balance(self, transaction_id: str) -> bool:
        """Verify that entries for a transaction sum to zero."""
        entries = self.get_entries_for_transaction(transaction_id)
        return sum(e["amount_cents"] for e in entries) == 0


# ============================================================
# Transaction Processor (Orchestrator)
# ============================================================

class TransactionProcessor:
    """Orchestrates payment processing across all services.

    Flow:
    1. Rate limit check
    2. Fraud detection
    3. Idempotency check
    4. Debit source account
    5. Credit destination account
    6. Record in ledger
    7. Return result

    If any step fails after debit, the debit is reversed.
    """

    def __init__(
        self,
        accounts: AccountService,
        rate_limiter: TokenBucketRateLimiter,
        fraud_detector: FraudDetector,
        ledger: AuditLedger,
    ):
        self.accounts = accounts
        self.rate_limiter = rate_limiter
        self.fraud_detector = fraud_detector
        self.ledger = ledger
        self._processed_keys: dict[str, Transaction] = {}  # idempotency_key -> result
        self._lock = Lock()

    def process_transfer(
        self,
        from_account_id: str,
        to_account_id: str,
        amount_cents: int,
        currency: str = "USD",
        idempotency_key: str | None = None,
        merchant_id: str = "default",
    ) -> Transaction:
        """Process a fund transfer between two accounts.

        This is the main entry point. It orchestrates all checks and
        the actual transfer atomically.
        """
        if amount_cents <= 0:
            raise PaymentError("Transfer amount must be positive")

        # Generate idempotency key if not provided
        if idempotency_key is None:
            idempotency_key = uuid.uuid4().hex

        # 1. Idempotency check
        with self._lock:
            if idempotency_key in self._processed_keys:
                return self._processed_keys[idempotency_key]

        # 2. Rate limit check
        if not self.rate_limiter.allow_request(merchant_id):
            raise RateLimitExceededError(
                f"Rate limit exceeded for merchant {merchant_id}"
            )

        # 3. Fraud detection
        from_account = self.accounts.get_account(from_account_id)
        fraud_result = self.fraud_detector.check_transaction(
            from_account, amount_cents,
        )
        if not fraud_result.approved:
            raise FraudDetectedError(
                f"Transaction rejected by fraud detection: {fraud_result.reason}"
            )

        # 4. Create transaction record
        txn = Transaction(
            id=uuid.uuid4().hex[:16],
            idempotency_key=idempotency_key,
            from_account=from_account_id,
            to_account=to_account_id,
            amount_cents=amount_cents,
            currency=currency,
            status=TransactionStatus.PENDING,
        )

        # 5. Execute transfer (debit then credit, with rollback)
        try:
            new_from_balance = self.accounts.debit(from_account_id, amount_cents)
        except PaymentError:
            txn.status = TransactionStatus.FAILED
            txn.failure_reason = "Debit failed"
            with self._lock:
                self._processed_keys[idempotency_key] = txn
            raise

        try:
            new_to_balance = self.accounts.credit(to_account_id, amount_cents)
        except PaymentError:
            # Rollback the debit
            self.accounts.credit(from_account_id, amount_cents)
            txn.status = TransactionStatus.FAILED
            txn.failure_reason = "Credit failed, debit reversed"
            with self._lock:
                self._processed_keys[idempotency_key] = txn
            raise

        # 6. Record in ledger
        self.ledger.record_transfer(
            transaction_id=txn.id,
            from_account_id=from_account_id,
            from_balance_after=new_from_balance,
            to_account_id=to_account_id,
            to_balance_after=new_to_balance,
            amount_cents=amount_cents,
        )

        # 7. Mark complete
        txn.status = TransactionStatus.COMPLETED
        txn.completed_at = time.time()

        with self._lock:
            self._processed_keys[idempotency_key] = txn

        logger.info(
            "Transfer completed: %s -> %s, amount=%d, txn=%s",
            from_account_id, to_account_id, amount_cents, txn.id,
        )
        return txn


# ============================================================
# Flask API (optional — works without Flask installed)
# ============================================================

def create_app() -> Any:
    """Create the Flask application. Only works if Flask is installed."""
    try:
        from flask import Flask, request, jsonify
    except ImportError:
        raise RuntimeError(
            "Flask is not installed. Install with: pip install flask"
        )

    app = Flask(__name__)

    # Initialize services
    accounts = AccountService()
    rate_limiter = TokenBucketRateLimiter(capacity=100, refill_rate=10.0)
    fraud_detector = FraudDetector()
    ledger = AuditLedger()
    processor = TransactionProcessor(accounts, rate_limiter, fraud_detector, ledger)

    @app.post("/accounts")
    def create_account():
        data = request.get_json()
        account = accounts.create_account(
            merchant_id=data["merchant_id"],
            initial_balance_cents=data.get("initial_balance_cents", 0),
            currency=data.get("currency", "USD"),
            overdraft_limit_cents=data.get("overdraft_limit_cents", 0),
        )
        return jsonify({"account_id": account.id, "balance_cents": account.balance_cents})

    @app.get("/accounts/<account_id>")
    def get_account(account_id: str):
        account = accounts.get_account(account_id)
        return jsonify({
            "id": account.id,
            "balance_cents": account.balance_cents,
            "currency": account.currency,
            "frozen": account.frozen,
        })

    @app.post("/transfers")
    def create_transfer():
        data = request.get_json()
        try:
            txn = processor.process_transfer(
                from_account_id=data["from_account"],
                to_account_id=data["to_account"],
                amount_cents=data["amount_cents"],
                currency=data.get("currency", "USD"),
                idempotency_key=data.get("idempotency_key"),
                merchant_id=data.get("merchant_id", "default"),
            )
            return jsonify({
                "transaction_id": txn.id,
                "status": txn.status.value,
                "amount_cents": txn.amount_cents,
            })
        except PaymentError as e:
            return jsonify({"error": str(e)}), 400

    @app.get("/transfers/<txn_id>/ledger")
    def get_ledger_entries(txn_id: str):
        entries = ledger.get_entries_for_transaction(txn_id)
        balanced = ledger.verify_balance(txn_id)
        return jsonify({"entries": entries, "balanced": balanced})

    return app


# ============================================================
# Standalone demo (no Flask required)
# ============================================================

def demo() -> None:
    """Run a demo of the payment system without Flask."""
    print("=== Payment API Demo ===\n")

    accounts = AccountService()
    rate_limiter = TokenBucketRateLimiter(capacity=100, refill_rate=10.0)
    fraud_detector = FraudDetector()
    ledger = AuditLedger()
    processor = TransactionProcessor(accounts, rate_limiter, fraud_detector, ledger)

    # Create accounts
    alice = accounts.create_account("merchant_1", initial_balance_cents=100_000)
    bob = accounts.create_account("merchant_1", initial_balance_cents=50_000)
    print(f"Alice: {alice.id} (balance: ${alice.balance_cents/100:.2f})")
    print(f"Bob:   {bob.id} (balance: ${bob.balance_cents/100:.2f})")

    # Transfer $250 from Alice to Bob
    txn = processor.process_transfer(
        from_account_id=alice.id,
        to_account_id=bob.id,
        amount_cents=25_000,
        merchant_id="merchant_1",
    )
    print(f"\nTransfer: ${txn.amount_cents/100:.2f} ({txn.status.value})")
    print(f"Alice: ${accounts.get_account(alice.id).balance_cents/100:.2f}")
    print(f"Bob:   ${accounts.get_account(bob.id).balance_cents/100:.2f}")

    # Verify ledger
    balanced = ledger.verify_balance(txn.id)
    print(f"\nLedger balanced: {balanced}")

    # Try overdraft
    print("\nAttempting overdraft...")
    try:
        processor.process_transfer(alice.id, bob.id, 1_000_000)
    except InsufficientFundsError as e:
        print(f"Blocked: {e}")

    print("\n=== Demo complete ===")


if __name__ == "__main__":
    demo()
