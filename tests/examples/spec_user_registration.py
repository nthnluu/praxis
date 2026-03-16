"""User registration spec — username must be non-empty, max 1000 users."""

from praxis import Spec, invariant, transition
from praxis.types import BoundedInt, Nat
from praxis.decorators import require


class UserRegistrationSpec(Spec):
    """A simple user registration system."""

    user_count: BoundedInt[0, 1000]
    username_length: Nat

    @invariant
    def max_users_not_exceeded(self):
        return self.user_count <= 1000

    @invariant
    def username_must_be_valid(self):
        return self.username_length > 0

    @transition
    def register(self, name_length: BoundedInt[1, 100]):
        require(self.user_count < 1000)
        self.username_length = name_length
        self.user_count += 1
