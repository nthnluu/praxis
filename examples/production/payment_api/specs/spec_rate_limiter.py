"""Rate Limiter Spec — token bucket for API rate limiting.

Proves that token count stays within [0, capacity] at all times.
"""

from praxis import Spec, invariant, transition
from praxis.types import BoundedInt
from praxis.decorators import require


class RateLimiterSpec(Spec):
    """Token bucket rate limiter."""

    tokens: BoundedInt[0, 1000]
    capacity: BoundedInt[1, 1000]

    @invariant
    def tokens_bounded(self):
        """Tokens never exceed capacity."""
        return self.tokens <= self.capacity

    @invariant
    def tokens_non_negative(self):
        """Tokens never go negative."""
        return self.tokens >= 0

    @transition
    def consume(self, cost: BoundedInt[1, 100]):
        """Consume tokens for an API request."""
        require(self.tokens >= cost)
        self.tokens -= cost

    @transition
    def refill(self, amount: BoundedInt[1, 100]):
        """Refill tokens, capped at capacity."""
        require(self.tokens + amount <= self.capacity)
        self.tokens += amount
