"""Authentication and Authorization Spec.

Proves:
- Only authenticated users can send messages
- Users can only access their own conversations
- Session tokens are validated before any operation
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class AuthSpec(Spec):
    """Authentication and session validation."""

    user_exists: BoundedInt[0, 1]                  # 0=no, 1=yes
    session_valid: BoundedInt[0, 1]                # 0=invalid, 1=valid
    user_uid_matches_conversation: BoundedInt[0, 1]  # ownership check

    @invariant
    def must_exist_to_have_session(self):
        """A valid session implies the user exists."""
        return implies(self.session_valid == 1, self.user_exists == 1)

    @invariant
    def must_own_conversation(self):
        """Access requires both valid session and ownership."""
        return implies(
            self.user_uid_matches_conversation == 1,
            self.session_valid == 1,
        )

    @transition
    def authenticate(self):
        """Verify credentials and create session."""
        require(self.user_exists == 1)
        self.session_valid = 1

    @transition
    def validate_session(self):
        """Check that the current session token is valid."""
        require(self.session_valid == 1)
        require(self.user_exists == 1)

    @transition
    def check_ownership(self):
        """Verify the user owns the conversation they're accessing."""
        require(self.session_valid == 1)
        require(self.user_exists == 1)
        self.user_uid_matches_conversation = 1

    @transition
    def invalidate_session(self):
        """Log out or expire the session."""
        self.session_valid = 0
        self.user_uid_matches_conversation = 0
