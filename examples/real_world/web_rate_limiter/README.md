# Web Rate Limiter

## The Problem

API rate limiting protects services from abuse and ensures fair resource sharing. The token bucket algorithm is the industry standard: each client has a bucket of tokens that refills over time. Each request consumes one or more tokens. When the bucket is empty, requests are rejected.

The two invariants that must hold: tokens never go negative (no overdraft), and tokens never exceed the bucket capacity (no overflow on refill). The overflow bug is subtle — a naive `tokens += refill_amount` without capping at capacity means a long-idle client accumulates unlimited tokens, then bursts at a rate far exceeding the limit. This defeats the entire purpose of rate limiting.

## The Implementation

`rate_limiter.py` — A `RateLimiter` using standard library only:

```python
class RateLimiter:
    def __init__(self, capacity: int, initial_tokens: int | None = None)
    def allow_request(self, cost: int = 1) -> bool
    def refill(self, amount: int) -> None
    def get_remaining(self) -> int
```

The `refill()` method caps at capacity: `self.tokens = min(self.tokens + amount, self.capacity)`. This is the critical line — without `min()`, the bucket overflows.

## Three Ways to Connect Spec and Implementation

Praxis offers three approaches for verifying that an implementation respects its spec. Use whichever fits your workflow -- or combine them.

### 1. Static verification (recommended first step)

Run `praxis check` to formally verify the spec with Z3. No implementation code is executed -- this proves the spec's transitions preserve its invariants for all possible inputs.

```bash
praxis check examples/real_world/web_rate_limiter/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest way to connect spec and implementation. The implementation stays unmodified; the spec connection lives entirely in the test file:

```python
import praxis
from examples.real_world.web_rate_limiter.rate_limiter import RateLimiter
from examples.real_world.web_rate_limiter.spec_rate_limiter import TokenBucketSpec

def test_invariants_hold():
    limiter = RateLimiter(capacity=20, initial_tokens=10)
    result = praxis.fuzz(
        limiter,
        TokenBucketSpec,
        state_extractor=lambda rl: {'tokens': rl.tokens, 'capacity': rl.capacity},
        operations=[
            lambda rl: rl.allow_request(cost=random.randint(1, 5)),
            lambda rl: rl.refill(amount=random.randint(1, 8)),
        ],
        iterations=10000,
    )
    assert result.passed, result
```

See `test_rate_limiter.py` for the full test suite.

### 3. Runtime monitoring (for production)

Attach spec checks to a class at startup -- no decorators needed on the implementation:

```python
import praxis

praxis.monitor(
    RateLimiter,
    TokenBucketSpec,
    state_extractor=lambda self: {'tokens': self.tokens, 'capacity': self.capacity},
    methods=["allow_request", "refill"],
    mode="log",   # or "enforce" to raise on violation
)
```

### 4. Per-method decorators (legacy, still supported)

Both `allow_request` and `refill` are currently decorated with `@runtime_guard`, which checks `TokenBucketSpec` invariants after each call:

```python
from praxis import runtime_guard

@runtime_guard(TokenBucketSpec, state_extractor=lambda self: {
    'tokens': self.tokens,
    'capacity': self.capacity,
})
def allow_request(self, cost: int = 1) -> bool: ...
```

The `state_extractor` maps directly -- the implementation uses the same field names as the spec. After every `allow_request` or `refill`, the guard verifies that tokens never go negative and never exceed capacity. If a bug in the implementation allowed tokens to overflow on refill, the guard would catch it immediately.

## The Spec

1. **`tokens_non_negative`**: `tokens >= 0`
2. **`tokens_within_capacity`**: `tokens <= capacity`

## The Bug Praxis Catches

In `broken/spec_rate_limiter.py`, `refill` has no capacity cap:

```python
@transition
def refill(self, amount: BoundedInt[1, 100]):
    # Missing: require(self.tokens + amount <= self.capacity)
    self.tokens += amount
```

Praxis finds a counterexample where a refill pushes tokens above capacity. For example: bucket with `capacity=1, tokens=0`, refill `amount=2` — tokens becomes 2, exceeding capacity. (Z3 may pick different concrete values on each run, but the violation pattern is the same.)

## Run It

```bash
# Static verification
praxis check examples/real_world/web_rate_limiter/
praxis check examples/real_world/web_rate_limiter/broken/

# Fuzz testing (recommended)
pytest examples/real_world/web_rate_limiter/test_rate_limiter.py -v

# All tests
pytest examples/real_world/web_rate_limiter/ -v
```
