"""BROKEN auth manager — unlock doesn't reset failure count.

Bug: _unlock() sets state back to LOGGED_OUT but forgets to reset
failed_attempts to 0. This means after admin unlock, the account
still has max failures recorded, violating the invariant that
locked_means_max_failures (the account is not locked but has
failures >= max_attempts, and any subsequent failure instantly
re-locks it).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field
from enum import IntEnum


class AuthState(IntEnum):
    LOGGED_OUT = 0
    LOGGED_IN = 1
    LOCKED = 2


@dataclass
class UserRecord:
    user_id: str
    password_hash: str
    salt: str
    state: AuthState = AuthState.LOGGED_OUT
    failed_attempts: int = 0
    locked_until: float | None = None


class AuthManager:
    def __init__(self, max_attempts: int = 5, lockout_duration: float = 300.0):
        self.max_attempts = max_attempts
        self.lockout_duration = lockout_duration
        self._users: dict[str, UserRecord] = {}

    def register(self, user_id: str, password: str) -> None:
        salt = os.urandom(32).hex()
        pw_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 100000).hex()
        self._users[user_id] = UserRecord(user_id=user_id, password_hash=pw_hash, salt=salt)

    def _unlock(self, user: UserRecord) -> None:
        """BUG: Doesn't reset failed_attempts!"""
        user.state = AuthState.LOGGED_OUT
        # user.failed_attempts = 0  # <-- MISSING! This is the bug.
        user.locked_until = None
