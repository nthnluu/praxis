"""Authentication State Machine Spec.

States: 0=logged_out, 1=logged_in, 2=locked_out
Proves:
- State is always valid (0, 1, or 2)
- Failed attempts are non-negative and bounded
- Lockout only happens after max failures
- Login resets failure count
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class AuthSpec(Spec):
    """Authentication with login, logout, lockout, and unlock."""

    state: BoundedInt[0, 2]              # 0=out, 1=in, 2=locked
    failed_attempts: BoundedInt[0, 10]
    max_attempts: BoundedInt[1, 10]

    @invariant
    def valid_state(self):
        return And(self.state >= 0, self.state <= 2)

    @invariant
    def failures_non_negative(self):
        return self.failed_attempts >= 0

    @invariant
    def locked_means_max_failures(self):
        """Lockout only when failed attempts reached max."""
        return implies(self.state == 2, self.failed_attempts >= self.max_attempts)

    @transition
    def login_success(self):
        """Successful login from logged-out state."""
        require(self.state == 0)
        self.state = 1
        self.failed_attempts = 0

    @transition
    def login_failure(self):
        """Failed login attempt."""
        require(self.state == 0)
        require(self.failed_attempts + 1 <= 10)
        self.failed_attempts += 1

    @transition
    def lockout(self):
        """Lock account after too many failures."""
        require(self.state == 0)
        require(self.failed_attempts >= self.max_attempts)
        self.state = 2

    @transition
    def logout(self):
        """Log out."""
        require(self.state == 1)
        self.state = 0

    @transition
    def unlock(self):
        """Admin unlocks a locked account."""
        require(self.state == 2)
        self.state = 0
        self.failed_attempts = 0
