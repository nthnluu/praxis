"""Authentication state machine with password hashing, sessions, and lockout.

A production-style auth manager that tracks login attempts, hashes passwords
with salt, issues session tokens, and locks accounts after too many failures.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from enum import IntEnum

from praxis import runtime_guard

try:
    from .spec_auth import AuthSpec
except ImportError:
    import importlib.util, pathlib
    _spec = importlib.util.spec_from_file_location(
        "spec_auth", pathlib.Path(__file__).parent / "spec_auth.py")
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    AuthSpec = _mod.AuthSpec


class AuthState(IntEnum):
    """Account authentication states."""
    LOGGED_OUT = 0
    LOGGED_IN = 1
    LOCKED = 2


@dataclass
class Session:
    """An active user session."""
    token: str
    user_id: str
    created_at: float
    expires_at: float

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass
class UserRecord:
    """Stored user credentials and state."""
    user_id: str
    password_hash: str
    salt: str
    state: AuthState = AuthState.LOGGED_OUT
    failed_attempts: int = 0
    locked_until: float | None = None
    last_login: float | None = None


class AuthError(Exception):
    """Base auth error."""
    pass


class InvalidCredentialsError(AuthError):
    pass


class AccountLockedError(AuthError):
    pass


class NotAuthenticatedError(AuthError):
    pass


class AuthManager:
    """Authentication manager with password hashing, sessions, and lockout.

    Features:
    - Argon2-style password hashing (using PBKDF2 with SHA-256)
    - Configurable lockout after N failed attempts
    - Session tokens with expiration
    - Account unlock after timeout
    """

    def __init__(
        self,
        max_attempts: int = 5,
        lockout_duration_seconds: float = 300.0,
        session_ttl_seconds: float = 3600.0,
        hash_iterations: int = 100_000,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if lockout_duration_seconds <= 0:
            raise ValueError("lockout_duration must be positive")

        self.max_attempts = max_attempts
        self.lockout_duration = lockout_duration_seconds
        self.session_ttl = session_ttl_seconds
        self.hash_iterations = hash_iterations

        self._users: dict[str, UserRecord] = {}
        self._sessions: dict[str, Session] = {}
        self._current_user: UserRecord | None = None  # Set by guarded methods

    def _auth_state(self) -> dict[str, int]:
        """Extract spec state from the current user being operated on."""
        user = self._current_user
        if user is None:
            return {'state': 0, 'failed_attempts': 0, 'max_attempts': self.max_attempts}
        return {
            'state': int(user.state),
            'failed_attempts': user.failed_attempts,
            'max_attempts': self.max_attempts,
        }

    def register(self, user_id: str, password: str) -> None:
        """Register a new user with a hashed password."""
        if user_id in self._users:
            raise AuthError(f"User '{user_id}' already exists")
        if len(password) < 8:
            raise AuthError("Password must be at least 8 characters")

        salt = os.urandom(32).hex()
        password_hash = self._hash_password(password, salt)
        self._users[user_id] = UserRecord(
            user_id=user_id,
            password_hash=password_hash,
            salt=salt,
        )

    @runtime_guard(AuthSpec, state_extractor=lambda self: self._auth_state())
    def login(self, user_id: str, password: str) -> str:
        """Authenticate a user and return a session token.

        Raises:
            InvalidCredentialsError: Wrong user_id or password.
            AccountLockedError: Account is locked due to too many failures.
        """
        user = self._get_user(user_id)
        self._current_user = user

        # Check if locked (and possibly auto-unlock)
        if user.state == AuthState.LOCKED:
            if user.locked_until and time.time() > user.locked_until:
                self._unlock(user)
            else:
                raise AccountLockedError(
                    f"Account '{user_id}' is locked. "
                    f"Try again after {user.locked_until}"
                )

        # Verify password
        candidate_hash = self._hash_password(password, user.salt)
        if not hmac.compare_digest(candidate_hash, user.password_hash):
            return self._handle_failed_login(user)

        # Success — reset failures, create session
        user.failed_attempts = 0
        user.state = AuthState.LOGGED_IN
        user.last_login = time.time()

        token = secrets.token_urlsafe(32)
        session = Session(
            token=token,
            user_id=user_id,
            created_at=time.time(),
            expires_at=time.time() + self.session_ttl,
        )
        self._sessions[token] = session
        return token

    @runtime_guard(AuthSpec, state_extractor=lambda self: self._auth_state())
    def logout(self, token: str) -> None:
        """Invalidate a session."""
        session = self._sessions.pop(token, None)
        if session:
            user = self._users.get(session.user_id)
            if user:
                self._current_user = user
                if user.state == AuthState.LOGGED_IN:
                    user.state = AuthState.LOGGED_OUT

    def validate_session(self, token: str) -> str:
        """Validate a session token and return the user_id.

        Raises:
            NotAuthenticatedError: Token is invalid or expired.
        """
        session = self._sessions.get(token)
        if session is None:
            raise NotAuthenticatedError("Invalid session token")
        if session.is_expired:
            self._sessions.pop(token, None)
            raise NotAuthenticatedError("Session expired")
        return session.user_id

    @runtime_guard(AuthSpec, state_extractor=lambda self: self._auth_state())
    def unlock_account(self, user_id: str) -> None:
        """Admin unlock — force-unlock a locked account."""
        user = self._get_user(user_id)
        self._current_user = user
        self._unlock(user)

    def get_state(self, user_id: str) -> AuthState:
        """Get the current auth state for a user."""
        return self._get_user(user_id).state

    def get_failed_attempts(self, user_id: str) -> int:
        """Get the current failed attempt count."""
        return self._get_user(user_id).failed_attempts

    # -- Internal --

    def _get_user(self, user_id: str) -> UserRecord:
        user = self._users.get(user_id)
        if user is None:
            raise InvalidCredentialsError("Invalid credentials")
        return user

    def _handle_failed_login(self, user: UserRecord) -> str:
        """Handle a failed login attempt. May lock the account."""
        user.failed_attempts += 1

        if user.failed_attempts >= self.max_attempts:
            user.state = AuthState.LOCKED
            user.locked_until = time.time() + self.lockout_duration
            raise AccountLockedError(
                f"Account '{user.user_id}' locked after "
                f"{user.failed_attempts} failed attempts"
            )

        raise InvalidCredentialsError(
            f"Invalid credentials. "
            f"{self.max_attempts - user.failed_attempts} attempts remaining"
        )

    def _unlock(self, user: UserRecord) -> None:
        """Unlock an account and reset failure counter."""
        user.state = AuthState.LOGGED_OUT
        user.failed_attempts = 0
        user.locked_until = None

    def _hash_password(self, password: str, salt: str) -> str:
        """Hash a password with PBKDF2-SHA256."""
        return hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt),
            self.hash_iterations,
        ).hex()
