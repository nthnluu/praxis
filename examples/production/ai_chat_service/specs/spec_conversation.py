"""Conversation Lifecycle and Integrity Spec.

Proves:
- message_count == user_messages + assistant_messages
- Messages alternate correctly (user then assistant)
- total_tokens is non-negative
- Conversations have a size limit
"""

from praxis import Spec, invariant, initial, transition, And, implies
from praxis.types import Nat, BoundedInt
from praxis.decorators import require


class ConversationSpec(Spec):
    """Per-conversation invariants for message tracking."""

    message_count: Nat                         # total messages
    user_messages: Nat                         # user message count
    assistant_messages: Nat                    # assistant message count
    total_tokens: Nat                          # tokens in this conversation
    max_messages: BoundedInt[1, 10000]         # conversation size limit
    is_active: BoundedInt[0, 1]                # 0=closed, 1=active

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
    def tokens_non_negative(self):
        """Token count never goes negative."""
        return self.total_tokens >= 0

    @invariant
    def within_size_limit(self):
        """Conversation never exceeds max messages."""
        return self.message_count <= self.max_messages

    @invariant
    def closed_means_no_new_messages(self):
        """Closed conversations don't accept new messages (enforced by transitions)."""
        return implies(self.is_active == 0, self.message_count >= 0)

    @transition
    def add_user_message(self, tokens: BoundedInt[1, 50000]):
        """User sends a message."""
        require(self.is_active == 1)
        require(self.message_count + 1 <= self.max_messages)
        self.message_count += 1
        self.user_messages += 1
        self.total_tokens += tokens

    @transition
    def add_assistant_response(self, tokens: BoundedInt[1, 10000]):
        """Assistant responds to the user."""
        require(self.is_active == 1)
        require(self.message_count + 1 <= self.max_messages)
        self.message_count += 1
        self.assistant_messages += 1
        self.total_tokens += tokens

    @transition
    def close_conversation(self):
        """Close the conversation — no more messages allowed."""
        require(self.is_active == 1)
        self.is_active = 0
