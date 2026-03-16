"""Broken rate limiter spec — refill doesn't cap at capacity.

Bug: refill transition allows tokens to exceed capacity because
the guard `tokens + amount <= capacity` is missing.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenTokenBucketSpec(Spec):
    tokens: BoundedInt[0, 1000]
    capacity: BoundedInt[1, 1000]

    @invariant
    def tokens_non_negative(self):
        return self.tokens >= 0

    @invariant
    def tokens_within_capacity(self):
        return self.tokens <= self.capacity

    @transition
    def allow_request(self, cost: BoundedInt[1, 100]):
        require(self.tokens >= cost)
        self.tokens -= cost

    @transition
    def refill(self, amount: BoundedInt[1, 100]):
        """BUG: Missing require(self.tokens + amount <= self.capacity)."""
        # Missing capacity check — tokens can exceed capacity
        self.tokens += amount
