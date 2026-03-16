# Authentication State Machine

## The Problem

Every web application needs authentication, and every authentication system is a state machine: users are logged out, logged in, or locked out. The transitions between these states have strict rules — you can't log in while locked, you shouldn't stay locked forever, and failed attempts must be tracked accurately.

The subtle bugs are in the edges. An admin unlocks an account but the failure counter isn't reset — the user gets instantly re-locked on their next typo. A session token isn't properly invalidated on logout, leaving a dangling auth. A lockout timeout check has an off-by-one that lets one extra attempt through.

These bugs pass unit tests because no one writes a test for "unlock then immediately fail once." They surface in production at 2 AM when a customer calls support because they can't log in even after an admin unlocked their account.

## The Implementation

`auth.py` — A production-style `AuthManager` using:
- **`hashlib.pbkdf2_hmac`** for password hashing with per-user salts
- **`secrets.token_urlsafe`** for session token generation
- **`hmac.compare_digest`** for timing-safe password comparison
- **`dataclasses`** for `UserRecord` and `Session` data structures

Key methods:
```python
class AuthManager:
    def register(self, user_id: str, password: str) -> None
    def login(self, user_id: str, password: str) -> str  # returns session token
    def logout(self, token: str) -> None
    def validate_session(self, token: str) -> str  # returns user_id
    def unlock_account(self, user_id: str) -> None
```

The manager tracks three states per user (`LOGGED_OUT`, `LOGGED_IN`, `LOCKED`), with configurable max attempts, lockout duration, and session TTL.

## The Spec

`spec_auth.py` defines three invariants:

1. **`valid_state`**: The auth state is always 0 (logged out), 1 (logged in), or 2 (locked). No invalid intermediate states.

2. **`failures_non_negative`**: The failed attempt counter never goes negative. Sounds trivial, but a misplaced decrement would break downstream logic.

3. **`locked_means_max_failures`**: If the account is locked, then `failed_attempts >= max_attempts`. This ensures lockout only happens when the threshold is actually reached — not prematurely.

Transitions model the state machine:
- `login_success`: logged_out → logged_in (resets failures)
- `login_failure`: increments counter (from logged_out state)
- `lockout`: logged_out → locked (requires failures >= threshold)
- `logout`: logged_in → logged_out
- `unlock`: locked → logged_out (resets failures)

## Three Ways to Connect Spec and Implementation

Praxis offers three approaches for verifying that an implementation respects its spec.

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/auth_state_machine/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives entirely in the test file, not in the implementation:

```python
import praxis
from examples.real_world.auth_state_machine.auth import AuthManager
from examples.real_world.auth_state_machine.spec_auth import AuthSpec

def test_auth_invariants():
    mgr = AuthManager(max_attempts=3, hash_iterations=1000)
    mgr.register("alice", "correct-horse-battery-staple")

    result = praxis.fuzz(
        mgr,
        AuthSpec,
        state_extractor=lambda m: {
            'state': int(m._users['alice'].state),
            'failed_attempts': m._users['alice'].failed_attempts,
            'max_attempts': m.max_attempts,
        },
        operations=[
            lambda m: m.login("alice", "correct-horse-battery-staple"),
            lambda m: m.login("alice", "wrong-password-1234"),
            lambda m: m.unlock_account("alice"),
        ],
        iterations=5000,
    )
    assert result.passed, result
```

See `test_auth.py` for the full test suite.

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    AuthManager,
    AuthSpec,
    state_extractor=lambda self: self._auth_state(),
    methods=["login", "logout", "unlock_account"],
    mode="log",   # or "enforce" to raise on violation
)
```

### 4. Per-method decorators (legacy, still supported)

The implementation currently uses `@runtime_guard` on `login`, `logout`, and `unlock_account`:

```python
from praxis import runtime_guard

class AuthManager:
    @runtime_guard(AuthSpec, state_extractor=lambda self: self._auth_state())
    def login(self, user_id: str, password: str) -> str: ...
```

The `state_extractor` maps the implementation's internal state to the spec's abstract variables:

| Spec variable      | Implementation source          |
|---------------------|-------------------------------|
| `state`            | `int(user.state)` (AuthState enum: 0/1/2) |
| `failed_attempts`  | `user.failed_attempts`         |
| `max_attempts`     | `self.max_attempts`            |

If a method leaves the system in a state that violates any spec invariant (e.g., unlocking an account without resetting the failure counter), the runtime guard raises an `AssertionError` immediately — before the bug can propagate.

## What Praxis Proves

For **every possible** combination of state, failure count, and max attempts:

1. The auth state is always one of the three valid values
2. Failed attempts never go negative
3. An account is only in the LOCKED state if failures actually reached the threshold
4. Every transition preserves all three invariants

## The Bug Praxis Catches

In `broken/`, the `unlock` transition forgets to reset `failed_attempts`:

```python
def _unlock(self, user: UserRecord) -> None:
    user.state = AuthState.LOGGED_OUT
    # user.failed_attempts = 0  # <-- MISSING!
    user.locked_until = None
```

Praxis finds this immediately:

```
INVARIANT VIOLATED: unlocked_means_below_threshold

  Counterexample:
    failed_attempts = 1
    max_attempts = 1
    state = 2

  After transition `unlock`:
    failed_attempts' = 1
    max_attempts' = 1
    state' = 0
```

Translation: an account with `max_attempts=1` that's locked with 1 failure gets unlocked, but still has 1 failure recorded. It's now in `LOGGED_OUT` state with `failed_attempts >= max_attempts` — violating the invariant. The next login failure will instantly re-lock it.

This bug is hard to catch with traditional testing because you'd need to test the specific sequence: register → fail enough to lock → admin unlock → check that failure count was reset. Most test suites test the happy path (register → login → logout) and maybe lockout, but not the unlock-then-verify-counter sequence.

## Run It

```bash
# Static verification
praxis check examples/real_world/auth_state_machine/
praxis check examples/real_world/auth_state_machine/broken/

# Fuzz testing (recommended)
pytest examples/real_world/auth_state_machine/test_auth.py -v

# All tests
pytest examples/real_world/auth_state_machine/ -v
```
