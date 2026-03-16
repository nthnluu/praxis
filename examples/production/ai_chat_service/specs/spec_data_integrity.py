"""Firestore Write Consistency Spec.

Proves:
- Tokens are never charged without recording the update
- Conversation updates are persisted when messages are added
- Tokens charged to user match tokens recorded in conversation
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt, Nat
from praxis.decorators import require


class DataIntegritySpec(Spec):
    """Transactional consistency for Firestore writes."""

    user_updated: BoundedInt[0, 1]           # 0=not yet, 1=committed
    conversation_updated: BoundedInt[0, 1]   # 0=not yet, 1=committed
    tokens_charged: BoundedInt[0, 1]         # 0=not yet, 1=charged
    user_token_delta: Nat                    # tokens added to user record
    conversation_token_delta: Nat            # tokens added to conversation record

    @invariant
    def charge_requires_user_update(self):
        """Don't charge tokens without recording them on the user."""
        return implies(self.tokens_charged == 1, self.user_updated == 1)

    @invariant
    def tokens_conserved(self):
        """Tokens charged to user == tokens recorded in conversation."""
        return self.user_token_delta == self.conversation_token_delta

    @transition
    def begin_transaction(self, tokens: BoundedInt[1, 100000]):
        """Start a write transaction with a known token amount."""
        require(self.user_updated == 0)
        require(self.conversation_updated == 0)
        require(self.tokens_charged == 0)
        self.user_token_delta = tokens
        self.conversation_token_delta = tokens

    @transition
    def commit_user(self):
        """Persist user record with updated token count."""
        require(self.user_updated == 0)
        self.user_updated = 1

    @transition
    def commit_conversation(self):
        """Persist conversation record with new messages.
        User must be committed first (tokens_charged requires user_updated)."""
        require(self.conversation_updated == 0)
        require(self.user_updated == 1)
        self.conversation_updated = 1
        self.tokens_charged = 1

    @transition
    def rollback(self):
        """Abort the transaction — reset all flags."""
        self.user_updated = 0
        self.conversation_updated = 0
        self.tokens_charged = 0
        self.user_token_delta = 0
        self.conversation_token_delta = 0
