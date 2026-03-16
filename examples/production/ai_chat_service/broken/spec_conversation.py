"""Broken Conversation Spec — add message without updating count.

Bug: add_user_message increments user_messages but NOT message_count,
violating the count_consistent invariant.

praxis check will find this:
  INVARIANT VIOLATED: count_consistent
    message_count = 0, user_messages = 1, assistant_messages = 0
    message_count (0) != user_messages + assistant_messages (1)
"""

from praxis import Spec, invariant, initial, transition, And
from praxis.types import Nat, BoundedInt
from praxis.decorators import require


class BrokenConversationSpec(Spec):
    """Conversation spec with a missing message_count increment."""

    message_count: Nat
    user_messages: Nat
    assistant_messages: Nat
    total_tokens: Nat
    max_messages: BoundedInt[1, 10000]
    is_active: BoundedInt[0, 1]

    @initial
    def empty_conversation(self):
        return And(
            self.message_count == 0,
            self.user_messages == 0,
            self.assistant_messages == 0,
            self.total_tokens == 0,
            self.is_active == 1,
        )

    @invariant
    def count_consistent(self):
        """Total messages = user + assistant messages."""
        return self.message_count == self.user_messages + self.assistant_messages

    @invariant
    def within_size_limit(self):
        return self.message_count <= self.max_messages

    @transition
    def add_user_message(self, tokens: BoundedInt[1, 50000]):
        """BUG: increments user_messages but forgets message_count."""
        require(self.is_active == 1)
        # Missing: self.message_count += 1
        self.user_messages += 1
        self.total_tokens += tokens

    @transition
    def add_assistant_response(self, tokens: BoundedInt[1, 10000]):
        """This one is correct for contrast."""
        require(self.is_active == 1)
        require(self.message_count + 1 <= self.max_messages)
        self.message_count += 1
        self.assistant_messages += 1
        self.total_tokens += tokens
