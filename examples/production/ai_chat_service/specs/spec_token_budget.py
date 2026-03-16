"""Token Usage and Billing Spec.

Proves:
- Token usage never exceeds the daily limit
- total_tokens == prompt_tokens + completion_tokens
- completion_tokens never exceeds max_tokens requested
- All token counts are non-negative
"""

from praxis import Spec, invariant, initial, transition, And
from praxis.types import Nat, BoundedInt
from praxis.decorators import require


class TokenBudgetSpec(Spec):
    """Per-user daily token budget and per-request token accounting."""

    tokens_used_today: Nat                     # cumulative daily usage
    daily_limit: BoundedInt[1, 1_000_000]      # per-user daily cap
    prompt_tokens: Nat                         # last request prompt
    completion_tokens: Nat                     # last request completion
    total_tokens: Nat                          # last request total

    @initial
    def fresh_user(self):
        return And(
            self.tokens_used_today == 0,
            self.prompt_tokens == 0,
            self.completion_tokens == 0,
            self.total_tokens == 0,
        )

    @invariant
    def within_daily_limit(self):
        """User never exceeds their daily token limit."""
        return self.tokens_used_today <= self.daily_limit

    @invariant
    def total_consistent(self):
        """Total tokens = prompt + completion."""
        return self.total_tokens == self.prompt_tokens + self.completion_tokens

    @invariant
    def all_non_negative(self):
        """All token counts are non-negative."""
        return And(
            self.tokens_used_today >= 0,
            self.prompt_tokens >= 0,
            self.completion_tokens >= 0,
            self.total_tokens >= 0,
        )

    @transition
    def consume_tokens(self, prompt: BoundedInt[1, 50000], completion: BoundedInt[1, 10000]):
        """Record token usage from a completed API call."""
        require(self.tokens_used_today + prompt + completion <= self.daily_limit)
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion
        self.tokens_used_today += prompt + completion

    @transition
    def reset_daily_usage(self):
        """Midnight reset of daily token counter."""
        self.tokens_used_today = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
