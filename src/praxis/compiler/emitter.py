"""Emitter — translates Praxis IR to Z3 expressions."""

from __future__ import annotations

import z3

from praxis.compiler.ir import (
    IRNode, Var, PrimedVar, Param, Const, BinOp, UnaryOp,
    Compare, BoolOp, IfExpr, Require, Assign, Return,
)


class EmitContext:
    """Context for emitting Z3 expressions.

    Tracks Z3 variable bindings for state fields and parameters.
    """

    def __init__(self):
        self.vars: dict[str, z3.ExprRef] = {}       # state vars
        self.primed: dict[str, z3.ExprRef] = {}      # primed state vars (after-state)
        self.params: dict[str, z3.ExprRef] = {}      # transition params
        self.constraints: list = []                    # type bound constraints
        self.primed_constraints: list = []             # type bound constraints for primed vars

    def add_state_var(self, name: str, praxis_type: type) -> None:
        """Add a state variable from a Praxis type."""
        var, bounds = praxis_type.to_z3(name)
        self.vars[name] = var
        self.constraints.extend(bounds)

    def add_primed_var(self, name: str, praxis_type: type) -> None:
        """Add a primed (after-state) variable."""
        var, bounds = praxis_type.to_z3(f"{name}'")
        self.primed[name] = var
        self.primed_constraints.extend(bounds)

    def add_param(self, name: str, praxis_type: type) -> None:
        """Add a transition parameter variable."""
        var, bounds = praxis_type.to_z3(f"param_{name}")
        self.params[name] = var
        self.constraints.extend(bounds)


def emit(node: IRNode, ctx: EmitContext) -> z3.ExprRef:
    """Translate an IR node to a Z3 expression."""
    if isinstance(node, Var):
        if node.name not in ctx.vars:
            raise KeyError(f"Unknown state variable: {node.name}")
        return ctx.vars[node.name]

    if isinstance(node, PrimedVar):
        if node.name not in ctx.primed:
            raise KeyError(f"Unknown primed variable: {node.name}")
        return ctx.primed[node.name]

    if isinstance(node, Param):
        if node.name not in ctx.params:
            raise KeyError(f"Unknown parameter: {node.name}")
        return ctx.params[node.name]

    if isinstance(node, Const):
        if isinstance(node.value, bool):
            return z3.BoolVal(node.value)
        if isinstance(node.value, int):
            return z3.IntVal(node.value)
        if isinstance(node.value, float):
            return z3.RealVal(node.value)
        raise TypeError(f"Unsupported constant type: {type(node.value)}")

    if isinstance(node, BinOp):
        left = emit(node.left, ctx)
        right = emit(node.right, ctx)
        ops = {
            "+": lambda l, r: l + r,
            "-": lambda l, r: l - r,
            "*": lambda l, r: l * r,
            "//": lambda l, r: l / r,  # Z3 int div is floor division for positive divisors.
            # NOTE: diverges from Python for negative divisors (Z3 uses Euclidean div).
            # All current specs use positive divisors (BoundedInt[1, N]).
            "%": lambda l, r: l % r,
        }
        if node.op not in ops:
            raise ValueError(f"Unknown binary operator: {node.op}")
        return ops[node.op](left, right)

    if isinstance(node, UnaryOp):
        operand = emit(node.operand, ctx)
        if node.op == "-":
            return -operand
        if node.op == "not":
            return z3.Not(operand)
        raise ValueError(f"Unknown unary operator: {node.op}")

    if isinstance(node, Compare):
        left = emit(node.left, ctx)
        right = emit(node.right, ctx)
        ops = {
            "<": lambda l, r: l < r,
            "<=": lambda l, r: l <= r,
            ">": lambda l, r: l > r,
            ">=": lambda l, r: l >= r,
            "==": lambda l, r: l == r,
            "!=": lambda l, r: l != r,
        }
        if node.op not in ops:
            raise ValueError(f"Unknown comparison operator: {node.op}")
        return ops[node.op](left, right)

    if isinstance(node, BoolOp):
        values = [emit(v, ctx) for v in node.values]
        if node.op == "and":
            return z3.And(*values)
        if node.op == "or":
            return z3.Or(*values)
        if node.op == "implies":
            assert len(values) == 2
            return z3.Implies(values[0], values[1])
        raise ValueError(f"Unknown boolean operator: {node.op}")

    if isinstance(node, IfExpr):
        test = emit(node.test, ctx)
        body = emit(node.body, ctx)
        orelse = emit(node.orelse, ctx)
        return z3.If(test, body, orelse)

    if isinstance(node, Return):
        return emit(node.value, ctx)

    if isinstance(node, Require):
        return emit(node.expr, ctx)

    if isinstance(node, Assign):
        return emit(node.value, ctx)

    raise TypeError(f"Cannot emit IR node type: {type(node).__name__}")
