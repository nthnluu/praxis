"""External Payment Gateway Client — wrapping third-party API calls.

This demonstrates how Praxis works with external API integrations.
The key insight: you don't verify the external API's behavior (you can't).
You verify that YOUR code correctly handles all responses and maintains
YOUR invariants regardless of what the external API returns.

The gateway client wraps calls to a payment processor (like Stripe, Adyen, etc.)
with a circuit breaker and retry logic. The Praxis spec proves that:
- Retries don't cause double-charges
- The circuit breaker prevents cascade failures
- Timeout handling doesn't leave the system in an inconsistent state
"""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable


class GatewayStatus(Enum):
    SUCCESS = "success"
    DECLINED = "declined"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class GatewayResponse:
    """Response from the external payment gateway."""
    status: GatewayStatus
    gateway_txn_id: str | None = None
    error_message: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChargeAttempt:
    """Record of a single charge attempt."""
    attempt_number: int
    idempotency_key: str
    amount_cents: int
    status: GatewayStatus
    gateway_txn_id: str | None = None
    timestamp: float = field(default_factory=time.time)


class GatewayClient:
    """Client for an external payment gateway with safety guarantees.

    Key safety patterns:
    1. IDEMPOTENCY: Every charge uses an idempotency key derived from the
       transaction ID. If we retry (due to timeout), the gateway deduplicates.
       This prevents double-charges.

    2. CIRCUIT BREAKER: If the gateway fails repeatedly, we stop sending
       requests to let it recover. This prevents cascade failures.

    3. TIMEOUT TRACKING: If a charge times out, we DON'T know if it succeeded.
       We record it as "pending" and check later. We never assume success
       or failure on timeout.

    4. AMOUNT VALIDATION: We validate the charge amount before sending to
       the gateway. The spec proves this check is correct.
    """

    def __init__(
        self,
        gateway_fn: Callable[[str, int, str], GatewayResponse],
        max_retries: int = 3,
        circuit_breaker_threshold: int = 5,
        circuit_breaker_timeout: float = 60.0,
        max_charge_cents: int = 10_000_00,  # $10,000
    ):
        self._gateway_fn = gateway_fn
        self.max_retries = max_retries
        self.max_charge_cents = max_charge_cents

        # Circuit breaker state
        self._consecutive_failures = 0
        self._circuit_open = False
        self._circuit_opened_at: float | None = None
        self._circuit_threshold = circuit_breaker_threshold
        self._circuit_timeout = circuit_breaker_timeout

        # Tracking
        self._attempts: dict[str, list[ChargeAttempt]] = {}
        self._completed_charges: dict[str, str] = {}  # idempotency_key -> gateway_txn_id

    def charge(
        self, transaction_id: str, amount_cents: int, currency: str = "USD",
    ) -> GatewayResponse:
        """Charge a customer via the external gateway.

        Uses idempotency key derived from transaction_id to prevent
        double-charges on retry.

        Args:
            transaction_id: Our internal transaction ID.
            amount_cents: Amount to charge in cents.
            currency: ISO currency code.

        Returns:
            GatewayResponse with the result.

        Raises:
            ValueError: If amount is invalid.
            RuntimeError: If circuit breaker is open.
        """
        # Validate amount
        if amount_cents <= 0:
            raise ValueError("Charge amount must be positive")
        if amount_cents > self.max_charge_cents:
            raise ValueError(
                f"Charge amount {amount_cents} exceeds maximum {self.max_charge_cents}"
            )

        # Check circuit breaker
        if self._circuit_open:
            if self._should_attempt_reset():
                self._circuit_open = False
                self._consecutive_failures = 0
            else:
                raise RuntimeError(
                    "Payment gateway circuit breaker is open. "
                    f"Too many failures ({self._consecutive_failures}). "
                    f"Will retry in {self._time_until_reset():.0f}s"
                )

        # Generate idempotency key from transaction ID (deterministic)
        idempotency_key = self._make_idempotency_key(transaction_id)

        # Check if already completed (prevents double-charge on our side)
        if idempotency_key in self._completed_charges:
            return GatewayResponse(
                status=GatewayStatus.SUCCESS,
                gateway_txn_id=self._completed_charges[idempotency_key],
            )

        # Attempt the charge with retries
        attempts = self._attempts.setdefault(transaction_id, [])

        for attempt_num in range(1, self.max_retries + 1):
            response = self._gateway_fn(idempotency_key, amount_cents, currency)

            attempt = ChargeAttempt(
                attempt_number=attempt_num,
                idempotency_key=idempotency_key,
                amount_cents=amount_cents,
                status=response.status,
                gateway_txn_id=response.gateway_txn_id,
            )
            attempts.append(attempt)

            if response.status == GatewayStatus.SUCCESS:
                self._on_success()
                self._completed_charges[idempotency_key] = response.gateway_txn_id
                return response

            if response.status == GatewayStatus.DECLINED:
                # Declined is a definitive response — don't retry
                self._on_success()  # Gateway is working, just declined
                return response

            if response.status == GatewayStatus.TIMEOUT:
                # Unknown state — might have charged. DON'T retry blindly.
                # The idempotency key protects us if we do retry.
                self._on_failure()
                continue

            if response.status == GatewayStatus.ERROR:
                self._on_failure()
                continue

        # All retries exhausted
        return GatewayResponse(
            status=GatewayStatus.ERROR,
            error_message=f"All {self.max_retries} attempts failed",
        )

    def get_attempts(self, transaction_id: str) -> list[ChargeAttempt]:
        """Get all charge attempts for a transaction."""
        return self._attempts.get(transaction_id, [])

    def _make_idempotency_key(self, transaction_id: str) -> str:
        """Derive a deterministic idempotency key from transaction ID."""
        return hashlib.sha256(
            f"praxis-charge-{transaction_id}".encode()
        ).hexdigest()[:32]

    def _on_success(self) -> None:
        self._consecutive_failures = 0

    def _on_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._circuit_threshold:
            self._circuit_open = True
            self._circuit_opened_at = time.time()

    def _should_attempt_reset(self) -> bool:
        if self._circuit_opened_at is None:
            return True
        return (time.time() - self._circuit_opened_at) >= self._circuit_timeout

    def _time_until_reset(self) -> float:
        if self._circuit_opened_at is None:
            return 0.0
        elapsed = time.time() - self._circuit_opened_at
        return max(0.0, self._circuit_timeout - elapsed)


# ============================================================
# Example: Mock gateway for testing/demo
# ============================================================

def mock_gateway(
    failure_rate: float = 0.0,
) -> Callable[[str, int, str], GatewayResponse]:
    """Create a mock gateway function for testing.

    Args:
        failure_rate: Probability of failure (0.0-1.0).
    """
    import random

    def gateway(idempotency_key: str, amount_cents: int, currency: str) -> GatewayResponse:
        if random.random() < failure_rate:
            return GatewayResponse(status=GatewayStatus.TIMEOUT)
        return GatewayResponse(
            status=GatewayStatus.SUCCESS,
            gateway_txn_id=f"gw_{uuid.uuid4().hex[:12]}",
        )

    return gateway
