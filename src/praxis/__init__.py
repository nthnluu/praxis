"""Praxis — Property-based verification for Python."""

from praxis.spec import Spec
from praxis.decorators import invariant, initial, transition, verify, require
from praxis.logic import And, Or, Not, implies, iff, forall, exists
from praxis.engine.target_verifier import runtime_guard
from praxis.bridge import fuzz, monitor

__all__ = [
    "Spec",
    "initial",
    "invariant",
    "transition",
    "verify",
    "require",
    "And",
    "Or",
    "Not",
    "implies",
    "iff",
    "forall",
    "exists",
    "runtime_guard",
    "fuzz",
    "monitor",
]
