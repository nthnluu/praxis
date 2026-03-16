"""Fuzz-test the AuthManager against AuthSpec.

Demonstrates the recommended praxis.fuzz() approach for a stateful
authentication system.  The spec connection lives entirely in the test;
the implementation only needs @runtime_guard if you want production
monitoring too.
"""

import random

import praxis
from examples.real_world.auth_state_machine.auth import (
    AuthManager,
    AuthState,
)
from examples.real_world.auth_state_machine.spec_auth import AuthSpec


USER = "testuser"
PASSWORD = "correct-horse-battery-staple"
BAD_PASSWORD = "wrong-password-1234"


def _make_manager(max_attempts: int = 3) -> AuthManager:
    """Create an AuthManager with a registered test user."""
    mgr = AuthManager(
        max_attempts=max_attempts,
        lockout_duration_seconds=0.1,
        session_ttl_seconds=3600,
        hash_iterations=1000,  # fast for tests
    )
    mgr.register(USER, PASSWORD)
    return mgr


def _state(mgr: AuthManager) -> dict:
    """Extract spec-compatible state from the manager."""
    try:
        user = mgr._users[USER]
    except KeyError:
        return {"state": 0, "failed_attempts": 0, "max_attempts": mgr.max_attempts}
    return {
        "state": int(user.state),
        "failed_attempts": user.failed_attempts,
        "max_attempts": mgr.max_attempts,
    }


class TestAuthFuzz:
    """Fuzz the AuthManager with random login/logout/unlock sequences."""

    def test_invariants_hold_under_fuzzing(self):
        mgr = _make_manager(max_attempts=3)

        def do_login_success(m):
            m.login(USER, PASSWORD)

        def do_login_failure(m):
            m.login(USER, BAD_PASSWORD)

        def do_logout(m):
            token = m.login(USER, PASSWORD)
            m.logout(token)

        def do_unlock(m):
            m.unlock_account(USER)

        result = praxis.fuzz(
            mgr,
            AuthSpec,
            state_extractor=_state,
            operations=[
                do_login_success,
                do_login_failure,
                do_logout,
                do_unlock,
            ],
            iterations=5000,
            seed=42,
        )
        assert result.passed, result

    def test_lockout_invariants(self):
        """Focus on the lockout path: fail enough times to lock, then unlock."""
        mgr = _make_manager(max_attempts=2)

        def do_login_failure(m):
            m.login(USER, BAD_PASSWORD)

        def do_unlock(m):
            m.unlock_account(USER)

        result = praxis.fuzz(
            mgr,
            AuthSpec,
            state_extractor=_state,
            operations=[
                do_login_failure,
                do_unlock,
            ],
            iterations=5000,
            seed=7,
        )
        assert result.passed, result
