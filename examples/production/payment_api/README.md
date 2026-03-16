# Production Payment API

A complete payment processing system demonstrating how Praxis verifies a production-scale application with multiple interacting components and external API integrations.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Flask API Layer                        │
│  POST /transfers    GET /accounts    GET /ledger         │
└────────────────────────┬────────────────────────────────┘
                         │
┌────────────────────────▼────────────────────────────────┐
│              Transaction Processor                       │
│  Orchestrates the full transfer flow:                    │
│  rate limit → fraud check → debit → credit → ledger     │
└──┬──────┬──────────┬────────────┬───────────┬───────────┘
   │      │          │            │           │
   ▼      ▼          ▼            ▼           ▼
┌──────┐┌──────┐┌─────────┐┌──────────┐┌──────────────┐
│Rate  ││Fraud ││Account  ││  Audit   ││   Gateway    │
│Limit ││Detect││Service  ││  Ledger  ││   Client     │
│      ││      ││         ││ (SQLite) ││ (External)   │
└──────┘└──────┘└─────────┘└──────────┘└──────────────┘
  spec_    spec_    spec_      spec_       spec_
  rate_    fraud   accounts    ledger      gateway
  limiter
```

Each component has its own Praxis spec. Together, they prove system-wide safety properties.

## The Components

### 1. Account Service (`app.py: AccountService`)
Manages account balances with thread-safe debit/credit operations and overdraft protection.

**Spec proves:** Balance never goes below overdraft limit. Frozen accounts reject all debits.

### 2. Rate Limiter (`app.py: TokenBucketRateLimiter`)
Per-merchant token bucket rate limiting with time-based refill.

**Spec proves:** Tokens never go negative. Tokens never exceed capacity.

### 3. Fraud Detector (`app.py: FraudDetector`)
Velocity-based fraud detection with per-transaction and time-window limits.

**Spec proves:** No approved transaction exceeds the per-txn limit. Total volume in a window never exceeds velocity limit.

### 4. Audit Ledger (`app.py: AuditLedger`)
SQLite-backed double-entry bookkeeping. Every transfer creates a debit and credit entry.

**Spec proves:** Total debits always equal total credits. Entries are consistent.

### 5. Transaction Processor (`app.py: TransactionProcessor`)
Orchestrates the full transfer flow with rollback on failure.

**Spec proves:** Money is neither created nor destroyed during transfers. Conservation law holds for all possible inputs.

### 6. Gateway Client (`gateway_client.py`)
Wraps calls to an external payment gateway (e.g., Stripe) with idempotency, retry logic, and circuit breaker.

**Spec proves:** Charge amounts never exceed limits. Retries are bounded. Circuit breaker only opens after threshold failures. Idempotency prevents double-charges.

## How Praxis Works With External APIs

The gateway client spec demonstrates a key Praxis pattern for external integrations:

**You can't verify what the external API does.** You verify that YOUR code handles ALL possible responses correctly.

```python
class GatewayClientSpec(Spec):
    charge_amount: BoundedInt[0, 1000000]
    max_charge: BoundedInt[1, 1000000]
    retry_count: BoundedInt[0, 10]
    consecutive_failures: BoundedInt[0, 100]
    circuit_open: BoundedInt[0, 1]

    @invariant
    def amount_within_limit(self):
        return self.charge_amount <= self.max_charge

    @invariant
    def circuit_opens_at_threshold(self):
        return implies(self.circuit_open == 1,
                       self.consecutive_failures >= self.circuit_threshold)

    @transition
    def gateway_failure(self, dummy: BoundedInt[0, 0]):
        """External API returned error — our handling is correct."""
        require(self.retry_count + 1 <= self.max_retries)
        self.retry_count += 1
        self.consecutive_failures += 1
```

The spec models each possible API response (success, failure, timeout) as a transition. Praxis proves that no matter what sequence of responses the external API returns, your system's invariants hold.

## The Bug Praxis Catches

In `broken/spec_transfer.py`, the transfer deducts from the source but doesn't credit the destination:

```
INVARIANT VIOLATED: conservation

  ┌─ Before ──────────────┐
  │ from_balance = 1      │
  │ to_balance = 0        │
  │ total_in_system = 1   │
  └───────────────────────┘
  ┌─ Input ──────┐
  │ amount = 1   │
  └──────────────┘
  ┌─ After ───────────────┐
  │ from_balance = 0      │
  │ to_balance = 0        │
  │ total_in_system = 1   │
  └───────────────────────┘
```

$1 vanished. `from_balance + to_balance = 0` but `total_in_system = 1`. This is exactly what happens when a transfer crashes between debit and credit without atomic transactions.

## Run It

```bash
# Run the standalone demo (no Flask required)
python examples/production/payment_api/app.py

# Verify ALL specs (6 components, 31 checks)
pytest examples/production/payment_api/specs/ -v

# Verify with the CLI
praxis check examples/production/payment_api/specs/

# JSON output for CI/agent integration
praxis check examples/production/payment_api/specs/ --format json

# See Praxis catch the broken transfer
praxis check examples/production/payment_api/broken/

# Run as Flask server (requires: pip install flask)
flask --app examples.production.payment_api.app run
```

## What This Demonstrates

1. **Component-level specs compose** — each service has its own spec, and together they prove system-wide properties
2. **External API safety** — the gateway client spec proves your error handling is correct regardless of what the external API does
3. **Conservation laws at scale** — the transfer spec proves money can never be created or destroyed, across all possible inputs
4. **Production patterns** — thread-safe operations, ACID transactions, circuit breakers, idempotency keys — all formally verified
