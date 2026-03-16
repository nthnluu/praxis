"""Lowering — translates Python AST nodes to Praxis IR."""

from __future__ import annotations

import ast

from praxis.compiler.ir import (
    IRNode, Var, PrimedVar, Param, Const, BinOp, UnaryOp,
    Compare, BoolOp, IfExpr, Require, Assign, Return,
)


class UnsupportedConstructError(Exception):
    """Raised when an unsupported Python construct is used in a spec method."""
    pass


_BINOP_MAP = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.FloorDiv: "//",
    ast.Mod: "%",
}

_CMPOP_MAP = {
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Eq: "==",
    ast.NotEq: "!=",
}


def lower_invariant(func_def: ast.FunctionDef) -> Return:
    """Lower an @invariant method body to IR.

    Expects the body to end with a return statement.
    """
    lowerer = _Lowerer(is_transition=False)
    return lowerer.lower_invariant(func_def)


def lower_transition(func_def: ast.FunctionDef, param_names: list[str]) -> list[IRNode]:
    """Lower a @transition method body to IR.

    Returns a list of IR nodes: Require nodes for preconditions,
    and Assign nodes for state mutations.
    """
    lowerer = _Lowerer(is_transition=True, param_names=param_names)
    return lowerer.lower_transition(func_def)


class _Lowerer:
    """Walks Python AST and produces Praxis IR."""

    def __init__(self, is_transition: bool = False, param_names: list[str] | None = None):
        self.is_transition = is_transition
        self.param_names = set(param_names or [])

    def lower_invariant(self, func_def: ast.FunctionDef) -> Return:
        """Lower an invariant function def — expects a return statement."""
        for stmt in func_def.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                continue  # skip docstrings
            if isinstance(stmt, ast.Return):
                return Return(value=self._lower_expr(stmt.value))
            self._reject(stmt)
        raise UnsupportedConstructError("Invariant must have a return statement")

    def lower_transition(self, func_def: ast.FunctionDef) -> list[IRNode]:
        """Lower a transition function def — require() calls and mutations."""
        nodes: list[IRNode] = []
        for stmt in func_def.body:
            if isinstance(stmt, ast.Pass):
                continue  # skip pass statements (no-op)
            if isinstance(stmt, ast.Expr):
                if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    continue  # skip docstrings
                if isinstance(stmt.value, ast.Call):
                    node = self._lower_call_stmt(stmt.value)
                    if node:
                        nodes.append(node)
                        continue
                self._reject(stmt)
            elif isinstance(stmt, ast.AugAssign):
                nodes.append(self._lower_aug_assign(stmt))
            elif isinstance(stmt, ast.Assign):
                nodes.append(self._lower_assign(stmt))
            else:
                self._reject(stmt)
        return nodes

    def _lower_call_stmt(self, call: ast.Call) -> IRNode | None:
        """Lower a call statement — only require() is supported."""
        if isinstance(call.func, ast.Name) and call.func.id == "require":
            if len(call.args) != 1:
                raise UnsupportedConstructError("require() takes exactly one argument")
            return Require(expr=self._lower_expr(call.args[0]))
        raise UnsupportedConstructError(
            f"Unsupported function call: {ast.dump(call.func)}. "
            "Only require() is allowed in spec methods."
        )

    def _lower_aug_assign(self, stmt: ast.AugAssign) -> Assign:
        """Lower self.x += expr to Assign(x, BinOp(+, Var(x), expr))."""
        if not (isinstance(stmt.target, ast.Attribute) and
                isinstance(stmt.target.value, ast.Name) and
                stmt.target.value.id == "self"):
            raise UnsupportedConstructError(
                "Augmented assignment is only supported on self.field"
            )
        field = stmt.target.attr
        op_type = type(stmt.op)
        if op_type not in _BINOP_MAP:
            raise UnsupportedConstructError(f"Unsupported augmented assignment operator: {op_type.__name__}")
        op = _BINOP_MAP[op_type]
        value = BinOp(op=op, left=Var(field), right=self._lower_expr(stmt.value))
        return Assign(target=field, value=value)

    def _lower_assign(self, stmt: ast.Assign) -> Assign:
        """Lower self.x = expr to Assign(x, expr)."""
        if len(stmt.targets) != 1:
            raise UnsupportedConstructError("Multiple assignment targets not supported")
        target = stmt.targets[0]
        if not (isinstance(target, ast.Attribute) and
                isinstance(target.value, ast.Name) and
                target.value.id == "self"):
            raise UnsupportedConstructError(
                "Assignment is only supported on self.field"
            )
        return Assign(target=target.attr, value=self._lower_expr(stmt.value))

    def _lower_expr(self, node: ast.expr) -> IRNode:
        """Lower a Python expression AST node to IR."""
        if isinstance(node, ast.Constant):
            return Const(value=node.value)

        if isinstance(node, ast.Name):
            if node.id in self.param_names:
                return Param(name=node.id)
            raise UnsupportedConstructError(
                f"Unsupported name reference: '{node.id}'. "
                "Use self.field for state variables or annotated parameters."
            )

        if isinstance(node, ast.Attribute):
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                return Var(name=node.attr)
            raise UnsupportedConstructError(
                f"Attribute access is only supported on 'self', got: {ast.dump(node.value)}"
            )

        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _BINOP_MAP:
                raise UnsupportedConstructError(f"Unsupported binary operator: {op_type.__name__}")
            return BinOp(
                op=_BINOP_MAP[op_type],
                left=self._lower_expr(node.left),
                right=self._lower_expr(node.right),
            )

        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return UnaryOp(op="-", operand=self._lower_expr(node.operand))
            if isinstance(node.op, ast.Not):
                return UnaryOp(op="not", operand=self._lower_expr(node.operand))
            raise UnsupportedConstructError(f"Unsupported unary operator: {type(node.op).__name__}")

        if isinstance(node, ast.Compare):
            # Handle chained comparisons: 0 <= x <= 100 -> And(0 <= x, x <= 100)
            if len(node.ops) == 1:
                op_type = type(node.ops[0])
                if op_type not in _CMPOP_MAP:
                    raise UnsupportedConstructError(f"Unsupported comparison: {op_type.__name__}")
                return Compare(
                    op=_CMPOP_MAP[op_type],
                    left=self._lower_expr(node.left),
                    right=self._lower_expr(node.comparators[0]),
                )
            # Chained: a op1 b op2 c -> And(a op1 b, b op2 c)
            parts = []
            left = node.left
            for op, right in zip(node.ops, node.comparators):
                op_type = type(op)
                if op_type not in _CMPOP_MAP:
                    raise UnsupportedConstructError(f"Unsupported comparison: {op_type.__name__}")
                parts.append(Compare(
                    op=_CMPOP_MAP[op_type],
                    left=self._lower_expr(left),
                    right=self._lower_expr(right),
                ))
                left = right
            return BoolOp(op="and", values=tuple(parts))

        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                return BoolOp(op="and", values=tuple(self._lower_expr(v) for v in node.values))
            if isinstance(node.op, ast.Or):
                return BoolOp(op="or", values=tuple(self._lower_expr(v) for v in node.values))
            raise UnsupportedConstructError(f"Unsupported boolean operator: {type(node.op).__name__}")

        if isinstance(node, ast.IfExp):
            return IfExpr(
                test=self._lower_expr(node.test),
                body=self._lower_expr(node.body),
                orelse=self._lower_expr(node.orelse),
            )

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                fn = node.func.id
                if fn == "require":
                    raise UnsupportedConstructError("require() cannot be used inside an expression")
                # Support Praxis logic functions: And, Or, Not, implies
                if fn == "And":
                    args = tuple(self._lower_expr(a) for a in node.args)
                    return BoolOp(op="and", values=args)
                if fn == "Or":
                    args = tuple(self._lower_expr(a) for a in node.args)
                    return BoolOp(op="or", values=args)
                if fn == "Not":
                    if len(node.args) != 1:
                        raise UnsupportedConstructError("Not() takes exactly one argument")
                    return UnaryOp(op="not", operand=self._lower_expr(node.args[0]))
                if fn == "implies":
                    if len(node.args) != 2:
                        raise UnsupportedConstructError("implies() takes exactly two arguments")
                    return BoolOp(op="implies", values=(
                        self._lower_expr(node.args[0]),
                        self._lower_expr(node.args[1]),
                    ))
            raise UnsupportedConstructError(
                f"Function calls are not supported in spec expressions. "
                f"Got: {ast.dump(node)}"
            )

        self._reject_expr(node)

    def _reject(self, node: ast.stmt) -> None:
        """Raise UnsupportedConstructError for an unsupported statement."""
        node_type = type(node).__name__
        details = {
            "For": "for loops are not supported in spec methods. Use forall() for quantification.",
            "While": "while loops are not supported in spec methods.",
            "Import": "import statements are not supported in spec methods.",
            "ImportFrom": "import statements are not supported in spec methods.",
            "Try": "try/except is not supported in spec methods.",
            "TryStar": "try/except is not supported in spec methods.",
            "AsyncFunctionDef": "async functions are not supported in spec methods.",
            "AsyncFor": "async for is not supported in spec methods.",
            "AsyncWith": "async with is not supported in spec methods.",
            "FunctionDef": "nested function definitions are not supported in spec methods.",
            "ClassDef": "class definitions are not supported in spec methods.",
            "With": "with statements are not supported in spec methods.",
        }
        msg = details.get(node_type, f"Unsupported construct: {node_type}")
        raise UnsupportedConstructError(msg)

    def _reject_expr(self, node: ast.expr) -> None:
        """Raise UnsupportedConstructError for an unsupported expression."""
        node_type = type(node).__name__
        details = {
            "ListComp": "list comprehensions are not supported in spec methods. Use forall()/exists() for quantification.",
            "SetComp": "set comprehensions are not supported in spec methods.",
            "DictComp": "dict comprehensions are not supported in spec methods.",
            "GeneratorExp": "generator expressions are not supported in spec methods.",
            "Lambda": "lambda expressions are not supported in spec methods.",
            "NamedExpr": "walrus operator (:=) is not supported in spec methods.",
            "Await": "await is not supported in spec methods.",
            "List": "list literals are not supported in spec methods.",
            "Dict": "dict literals are not supported in spec methods.",
            "Set": "set literals are not supported in spec methods.",
            "Tuple": "tuple literals are not supported in spec methods.",
            "Subscript": "subscript access is not supported in spec methods.",
        }
        msg = details.get(node_type, f"Unsupported expression: {node_type}")
        raise UnsupportedConstructError(msg)
