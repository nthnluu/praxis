"""Broken Token Budget Spec — send_message without budget check.

Bug: consume_tokens does not check that the new total stays within
the daily limit, violating the within_daily_limit invariant.

praxis check will find this:
  INVARIANT VIOLATED: within_daily_limit
    tokens_used_today = 999990, daily_limit = 1000000
    After consume_tokens(prompt=8000, completion=5000):
      tokens_used_today' = 1012990 > daily_limit (1000000)
"""

from praxis import Spec, invariant, initial, transition, And
from praxis.types import Nat, BoundedInt
from praxis.decorators import require


class BrokenTokenBudgetSpec(Spec):
    """Token budget WITHOUT the critical budget check."""

    tokens_used_today: Nat
    daily_limit: BoundedInt[1, 1_000_000]
    prompt_tokens: Nat
    completion_tokens: Nat
    total_tokens: Nat

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
        return self.total_tokens == self.prompt_tokens + self.completion_tokens

    @transition
    def consume_tokens(self, prompt: BoundedInt[1, 50000], completion: BoundedInt[1, 10000]):
        """BUG: No budget check — tokens can exceed daily limit."""
        # Missing: require(self.tokens_used_today + prompt + completion <= self.daily_limit)
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = prompt + completion
        self.tokens_used_today += prompt + completion
