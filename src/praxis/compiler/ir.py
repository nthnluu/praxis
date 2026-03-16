"""Praxis IR — intermediate representation for constraint compilation."""

from __future__ import annotations

from dataclasses import dataclass


class IRNode:
    """Base class for all IR nodes."""
    pass


@dataclass(frozen=True)
class Var(IRNode):
    """A state variable reference (e.g., self.x)."""
    name: str


@dataclass(frozen=True)
class PrimedVar(IRNode):
    """A primed state variable (after-state, e.g., x')."""
    name: str


@dataclass(frozen=True)
class Param(IRNode):
    """A transition parameter reference."""
    name: str


@dataclass(frozen=True)
class Const(IRNode):
    """A constant value."""
    value: int | float | bool


@dataclass(frozen=True)
class BinOp(IRNode):
    """Binary operation: left op right."""
    op: str  # '+', '-', '*', '//', '%'
    left: IRNode
    right: IRNode


@dataclass(frozen=True)
class UnaryOp(IRNode):
    """Unary operation: op operand."""
    op: str  # '-', 'not'
    operand: IRNode


@dataclass(frozen=True)
class Compare(IRNode):
    """Comparison: left op right."""
    op: str  # '<', '<=', '>', '>=', '==', '!='
    left: IRNode
    right: IRNode


@dataclass(frozen=True)
class BoolOp(IRNode):
    """Boolean operation: op over values."""
    op: str  # 'and', 'or'
    values: tuple[IRNode, ...]


@dataclass(frozen=True)
class IfExpr(IRNode):
    """Ternary if expression: body if test else orelse."""
    test: IRNode
    body: IRNode
    orelse: IRNode


@dataclass(frozen=True)
class Quantifier(IRNode):
    """Quantifier: forall or exists over a range with a predicate."""
    kind: str  # 'forall', 'exists'
    var_name: str
    lo: IRNode
    hi: IRNode
    body: IRNode


@dataclass(frozen=True)
class Require(IRNode):
    """A require() precondition."""
    expr: IRNode


@dataclass(frozen=True)
class Assign(IRNode):
    """Assignment to a primed variable: target' = value."""
    target: str  # state field name
    value: IRNode


@dataclass(frozen=True)
class Return(IRNode):
    """Return expression (invariant body)."""
    value: IRNode
