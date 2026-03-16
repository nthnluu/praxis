"""Token bucket rate limiter implementation."""

from praxis import runtime_guard
from examples.real_world.web_rate_limiter.spec_rate_limiter import TokenBucketSpec


class RateLimiter:
    """A token bucket rate limiter for API endpoints."""

    def __init__(self, capacity: int, initial_tokens: int | None = None):
        if capacity < 1:
            raise ValueError("Capacity must be at least 1")
        self.capacity = capacity
        self.tokens = initial_tokens if initial_tokens is not None else capacity

    @runtime_guard(TokenBucketSpec, state_extractor=lambda self: {
        'tokens': self.tokens,
        'capacity': self.capacity,
    })
    def allow_request(self, cost: int = 1) -> bool:
        """Try to consume tokens for a request. Returns True if allowed."""
        if cost < 1:
            raise ValueError("Cost must be at least 1")
        if self.tokens >= cost:
            self.tokens -= cost
            return True
        return False

    @runtime_guard(TokenBucketSpec, state_extractor=lambda self: {
        'tokens': self.tokens,
        'capacity': self.capacity,
    })
    def refill(self, amount: int) -> None:
        """Add tokens back, capped at capacity."""
        if amount < 1:
            raise ValueError("Refill amount must be at least 1")
        self.tokens = min(self.tokens + amount, self.capacity)

    def get_remaining(self) -> int:
        """Return current token count."""
        return self.tokens
