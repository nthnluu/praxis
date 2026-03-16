"""Rate Limiter Spec — token bucket for an API gateway.

Proves:
- Token count never goes negative
- Token count never exceeds bucket capacity
- Refill never overshoots max
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class TokenBucketSpec(Spec):
    """Token bucket rate limiter with bounded capacity."""

    tokens: BoundedInt[0, 1000]
    capacity: BoundedInt[1, 1000]

    @invariant
    def tokens_non_negative(self):
        """Token count is never negative."""
        return self.tokens >= 0

    @invariant
    def tokens_within_capacity(self):
        """Token count never exceeds bucket capacity."""
        return self.tokens <= self.capacity

    @transition
    def allow_request(self, cost: BoundedInt[1, 100]):
        """Consume tokens for an API request."""
        require(self.tokens >= cost)
        self.tokens -= cost

    @transition
    def refill(self, amount: BoundedInt[1, 100]):
        """Refill tokens up to capacity."""
        require(self.tokens + amount <= self.capacity)
        self.tokens += amount
