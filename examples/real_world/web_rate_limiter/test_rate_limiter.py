"""Fuzz-test the RateLimiter against TokenBucketSpec.

Demonstrates the recommended praxis.fuzz() approach: the implementation
stays decorator-free in tests, and the spec connection is made here.
"""

import random

import praxis
from examples.real_world.web_rate_limiter.rate_limiter import RateLimiter
from examples.real_world.web_rate_limiter.spec_rate_limiter import TokenBucketSpec


def _state(limiter: RateLimiter) -> dict:
    return {
        "tokens": limiter.tokens,
        "capacity": limiter.capacity,
    }


class TestRateLimiterFuzz:
    """Fuzz the RateLimiter with random allow/refill sequences."""

    def test_invariants_hold_under_fuzzing(self):
        limiter = RateLimiter(capacity=20, initial_tokens=10)

        result = praxis.fuzz(
            limiter,
            TokenBucketSpec,
            state_extractor=_state,
            operations=[
                lambda rl: rl.allow_request(cost=random.randint(1, 5)),
                lambda rl: rl.refill(amount=random.randint(1, 8)),
            ],
            iterations=10000,
            seed=42,
        )
        assert result.passed, result

    def test_empty_bucket_stays_valid(self):
        limiter = RateLimiter(capacity=5, initial_tokens=0)

        result = praxis.fuzz(
            limiter,
            TokenBucketSpec,
            state_extractor=_state,
            operations=[
                lambda rl: rl.allow_request(cost=1),
                lambda rl: rl.refill(amount=random.randint(1, 3)),
            ],
            iterations=5000,
            seed=99,
        )
        assert result.passed, result

    def test_full_bucket_stays_valid(self):
        limiter = RateLimiter(capacity=10, initial_tokens=10)

        result = praxis.fuzz(
            limiter,
            TokenBucketSpec,
            state_extractor=_state,
            operations=[
                lambda rl: rl.refill(amount=random.randint(1, 10)),
                lambda rl: rl.allow_request(cost=random.randint(1, 3)),
            ],
            iterations=5000,
            seed=7,
        )
        assert result.passed, result
