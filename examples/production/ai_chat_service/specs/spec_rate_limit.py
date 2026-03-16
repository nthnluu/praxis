"""API Rate Limiting Spec.

Proves:
- Requests per minute never exceed the cap
- Tokens per minute never exceed the cap
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class RateLimitSpec(Spec):
    """Per-user rate limiting by request count and token volume."""

    requests_this_minute: BoundedInt[0, 1000]
    max_requests_per_minute: BoundedInt[1, 1000]
    tokens_this_minute: BoundedInt[0, 1_000_000]
    max_tokens_per_minute: BoundedInt[1, 1_000_000]

    @invariant
    def requests_within_limit(self):
        """Request count never exceeds per-minute cap."""
        return self.requests_this_minute <= self.max_requests_per_minute

    @invariant
    def tokens_within_limit(self):
        """Token volume never exceeds per-minute cap."""
        return self.tokens_this_minute <= self.max_tokens_per_minute

    @transition
    def allow_request(self, tokens: BoundedInt[1, 100000]):
        """Allow a request — checks both rate and token limits."""
        require(self.requests_this_minute + 1 <= self.max_requests_per_minute)
        require(self.tokens_this_minute + tokens <= self.max_tokens_per_minute)
        self.requests_this_minute += 1
        self.tokens_this_minute += tokens

    @transition
    def reset_window(self):
        """Reset counters at the start of a new minute."""
        self.requests_this_minute = 0
        self.tokens_this_minute = 0
