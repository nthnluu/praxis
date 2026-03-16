"""Decorators for marking spec methods and preconditions."""

from __future__ import annotations

from typing import Any


def invariant(method=None, *, message: str | None = None):
    """Mark a method as a spec invariant.

    Can be used as @invariant or @invariant(message="...").
    """
    def decorator(fn):
        fn._praxis_invariant = True
        fn._praxis_invariant_message = message
        return fn

    if method is not None:
        # Used as @invariant (no parens)
        return decorator(method)
    # Used as @invariant(message="...")
    return decorator


def transition(method):
    """Mark a method as a state transition."""
    method._praxis_transition = True
    return method


def verify(target: str):
    """Mark a method as a verification binding for a target function.

    Args:
        target: Dotted path to the function to verify.
    """
    def decorator(method):
        method._praxis_verify = True
        method._praxis_verify_target = target
        return method
    return decorator


def initial(method):
    """Mark a method as an initial state predicate.

    The method should return a boolean expression over state fields that
    characterizes valid initial states. During verification, Praxis checks
    that every initial state satisfies all invariants (induction base case).
    """
    method._praxis_initial = True
    return method


def require(expr: Any) -> None:
    """Assert a precondition.

    During concrete execution, raises AssertionError if expr is falsy.
    During symbolic execution, the compiler extracts this as a Z3 precondition.
    """
    if not expr:
        raise AssertionError(f"Precondition violated: require({expr!r})")
