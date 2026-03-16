"""Logical combinators that work with both Python bools and Z3 expressions."""

from __future__ import annotations

import z3

_UNROLL_THRESHOLD = 50


def _is_z3(x: object) -> bool:
    """Check if x is a Z3 expression."""
    return isinstance(x, z3.ExprRef)


def And(*args):
    """Logical AND — works on Python bools and Z3 expressions."""
    if not args:
        return True
    if any(_is_z3(a) for a in args):
        return z3.And(*(a if _is_z3(a) else z3.BoolVal(bool(a)) for a in args))
    return all(args)


def Or(*args):
    """Logical OR — works on Python bools and Z3 expressions."""
    if not args:
        return False
    if any(_is_z3(a) for a in args):
        return z3.Or(*(a if _is_z3(a) else z3.BoolVal(bool(a)) for a in args))
    return any(args)


def Not(a):
    """Logical NOT — works on Python bools and Z3 expressions."""
    if _is_z3(a):
        return z3.Not(a)
    return not a


def implies(a, b):
    """Logical implication: a -> b."""
    if _is_z3(a) or _is_z3(b):
        a_z3 = a if _is_z3(a) else z3.BoolVal(bool(a))
        b_z3 = b if _is_z3(b) else z3.BoolVal(bool(b))
        return z3.Implies(a_z3, b_z3)
    return (not a) or bool(b)


def iff(a, b):
    """Logical biconditional: a <-> b (a if and only if b)."""
    if _is_z3(a) or _is_z3(b):
        a_z3 = a if _is_z3(a) else z3.BoolVal(bool(a))
        b_z3 = b if _is_z3(b) else z3.BoolVal(bool(b))
        return z3.And(z3.Implies(a_z3, b_z3), z3.Implies(b_z3, a_z3))
    return bool(a) == bool(b)


def forall(range_obj, predicate):
    """Universal quantification over a bounded range.

    Unrolls to z3.And for ranges <= 50, uses z3.ForAll for larger.
    Empty range returns True (vacuous truth).
    """
    items = list(range_obj)
    if not items:
        return True
    if len(items) <= _UNROLL_THRESHOLD:
        results = [predicate(i) for i in items]
        if any(_is_z3(r) for r in results):
            return z3.And(*(r if _is_z3(r) else z3.BoolVal(bool(r)) for r in results))
        return all(results)
    i = z3.Int("_forall_i")
    lo, hi = items[0], items[-1]
    body = predicate(i)
    return z3.ForAll([i], z3.Implies(z3.And(i >= lo, i <= hi), body))


def exists(range_obj, predicate):
    """Existential quantification over a bounded range.

    Unrolls to z3.Or for ranges <= 50, uses z3.Exists for larger.
    Empty range returns False.
    """
    items = list(range_obj)
    if not items:
        return False
    if len(items) <= _UNROLL_THRESHOLD:
        results = [predicate(i) for i in items]
        if any(_is_z3(r) for r in results):
            return z3.Or(*(r if _is_z3(r) else z3.BoolVal(bool(r)) for r in results))
        return any(results)
    i = z3.Int("_exists_i")
    lo, hi = items[0], items[-1]
    body = predicate(i)
    return z3.Exists([i], z3.And(z3.And(i >= lo, i <= hi), body))
