"""Broken auth spec — unlock transition doesn't reset failures.

This spec is identical to the correct one but demonstrates that Praxis
catches the broken unlock: after unlock, the state is LOGGED_OUT (0)
but failed_attempts still >= max_attempts, which means the NEXT login
failure will immediately re-lock without going through the threshold.

The invariant `locked_means_max_failures` requires that ONLY locked
accounts have failures >= threshold. The broken unlock violates this.
"""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenAuthSpec(Spec):
    """Auth spec where unlock forgets to reset failure count."""

    state: BoundedInt[0, 2]
    failed_attempts: BoundedInt[0, 10]
    max_attempts: BoundedInt[1, 10]

    @invariant
    def valid_state(self):
        return And(self.state >= 0, self.state <= 2)

    @invariant
    def failures_non_negative(self):
        return self.failed_attempts >= 0

    @invariant
    def unlocked_means_below_threshold(self):
        """If NOT locked, failures must be below threshold."""
        return implies(self.state != 2, self.failed_attempts < self.max_attempts)

    @transition
    def login_failure(self):
        require(self.state == 0)
        require(self.failed_attempts + 1 <= 10)
        self.failed_attempts += 1

    @transition
    def lockout(self):
        require(self.state == 0)
        require(self.failed_attempts >= self.max_attempts)
        self.state = 2

    @transition
    def unlock(self):
        """BUG: doesn't reset failed_attempts."""
        require(self.state == 2)
        self.state = 0
        # Missing: self.failed_attempts = 0
