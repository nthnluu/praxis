"""Rate limiter specification — token bucket pattern."""

from praxis import Spec, invariant, transition
from praxis.types import BoundedInt
from praxis.decorators import require


class RateLimiterSpec(Spec):
    """Token bucket: tokens in [0, max_tokens]."""

    tokens: BoundedInt[0, 1000]
    max_tokens: BoundedInt[1, 1000]

    @invariant
    def tokens_within_limit(self):
        return self.tokens <= self.max_tokens

    @invariant
    def tokens_non_negative(self):
        return self.tokens >= 0

    @transition
    def consume(self, n: BoundedInt[1, 100]):
        require(self.tokens >= n)
        self.tokens -= n

    @transition
    def refill(self, n: BoundedInt[1, 100]):
        require(self.tokens + n <= self.max_tokens)
        self.tokens += n
