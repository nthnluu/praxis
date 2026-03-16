"""Broken chat service spec — send_message doesn't check token budget.

Bug: the transition consumes tokens without checking the daily limit,
violating the within_budget invariant.
"""

from praxis import Spec, invariant, initial, transition, require, And
from praxis.types import Nat, BoundedInt


class BrokenChatServiceSpec(Spec):
    tokens_used: Nat
    daily_limit: BoundedInt[1, 1_000_000]
    conversation_count: Nat
    active_conversations: Nat

    @initial
    def fresh_user(self):
        return And(self.tokens_used == 0, self.conversation_count == 0)

    @invariant
    def within_budget(self):
        return self.tokens_used <= self.daily_limit

    @invariant
    def non_negative(self):
        return And(self.tokens_used >= 0, self.conversation_count >= 0)

    @transition
    def send_message(self, tokens: BoundedInt[1, 10000]):
        """BUG: No budget check — tokens can exceed daily limit."""
        # Missing: require(self.tokens_used + tokens <= self.daily_limit)
        self.tokens_used += tokens
