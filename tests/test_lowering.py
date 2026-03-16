"""Tests for praxis.compiler.lowering."""

import ast
import pytest
import textwrap

from praxis.compiler.lowering import (
    lower_invariant, lower_transition, UnsupportedConstructError,
)
from praxis.compiler.ir import (
    Var, Param, Const, BinOp, UnaryOp, Compare, BoolOp, IfExpr,
    Require, Assign, Return,
)


def _parse_func(source: str) -> ast.FunctionDef:
    source = textwrap.dedent(source)
    tree = ast.parse(source)
    return tree.body[0]


class TestLowerInvariant:
    def test_simple_comparison(self):
        func = _parse_func("""
            def inv(self):
                return self.x >= 0
        """)
        result = lower_invariant(func)
        assert isinstance(result, Return)
        assert isinstance(result.value, Compare)
        assert result.value.op == ">="

    def test_arithmetic(self):
        func = _parse_func("""
            def inv(self):
                return self.x + self.y <= 200
        """)
        result = lower_invariant(func)
        cmp = result.value
        assert isinstance(cmp, Compare)
        assert isinstance(cmp.left, BinOp)
        assert cmp.left.op == "+"

    def test_boolean_and(self):
        func = _parse_func("""
            def inv(self):
                return self.x >= 0 and self.y >= 0
        """)
        result = lower_invariant(func)
        assert isinstance(result.value, BoolOp)
        assert result.value.op == "and"

    def test_boolean_or(self):
        func = _parse_func("""
            def inv(self):
                return self.x >= 0 or self.y >= 0
        """)
        result = lower_invariant(func)
        assert isinstance(result.value, BoolOp)
        assert result.value.op == "or"

    def test_not(self):
        func = _parse_func("""
            def inv(self):
                return not self.x >= 0
        """)
        result = lower_invariant(func)
        assert isinstance(result.value, UnaryOp)
        assert result.value.op == "not"

    def test_ternary(self):
        func = _parse_func("""
            def inv(self):
                return self.x if self.y > 0 else self.z
        """)
        result = lower_invariant(func)
        assert isinstance(result.value, IfExpr)

    def test_chained_comparison(self):
        func = _parse_func("""
            def inv(self):
                return 0 <= self.x <= 100
        """)
        result = lower_invariant(func)
        assert isinstance(result.value, BoolOp)
        assert result.value.op == "and"
        assert len(result.value.values) == 2

    def test_compound_expression(self):
        func = _parse_func("""
            def inv(self):
                return (self.x + self.y) * 2 <= self.z - 1
        """)
        result = lower_invariant(func)
        cmp = result.value
        assert isinstance(cmp, Compare)
        assert isinstance(cmp.left, BinOp)
        assert cmp.left.op == "*"

    def test_all_arithmetic_ops(self):
        for op_str, py_op in [("//", "//"), ("%", "%"), ("*", "*"), ("-", "-")]:
            func = _parse_func(f"""
                def inv(self):
                    return self.x {py_op} self.y >= 0
            """)
            result = lower_invariant(func)
            cmp = result.value
            assert isinstance(cmp.left, BinOp)
            assert cmp.left.op == op_str

    def test_unary_minus(self):
        func = _parse_func("""
            def inv(self):
                return -self.x <= 0
        """)
        result = lower_invariant(func)
        assert isinstance(result.value.left, UnaryOp)
        assert result.value.left.op == "-"

    def test_constants(self):
        func = _parse_func("""
            def inv(self):
                return self.x >= 42
        """)
        result = lower_invariant(func)
        assert isinstance(result.value.right, Const)
        assert result.value.right.value == 42

    def test_docstring_skipped(self):
        func = _parse_func("""
            def inv(self):
                \"\"\"This is a docstring.\"\"\"
                return self.x >= 0
        """)
        result = lower_invariant(func)
        assert isinstance(result, Return)

    def test_all_comparison_ops(self):
        for op in ["<", "<=", ">", ">=", "==", "!="]:
            func = _parse_func(f"""
                def inv(self):
                    return self.x {op} self.y
            """)
            result = lower_invariant(func)
            assert result.value.op == op


class TestLowerTransition:
    def test_require(self):
        func = _parse_func("""
            def trans(self, delta):
                require(self.x + delta >= 0)
                self.x += delta
        """)
        nodes = lower_transition(func, ["delta"])
        assert isinstance(nodes[0], Require)
        assert isinstance(nodes[1], Assign)

    def test_aug_assign(self):
        func = _parse_func("""
            def trans(self, delta):
                self.x += delta
        """)
        nodes = lower_transition(func, ["delta"])
        assert len(nodes) == 1
        assign = nodes[0]
        assert isinstance(assign, Assign)
        assert assign.target == "x"
        assert isinstance(assign.value, BinOp)
        assert assign.value.op == "+"

    def test_plain_assign(self):
        func = _parse_func("""
            def trans(self, val):
                self.x = val
        """)
        nodes = lower_transition(func, ["val"])
        assert isinstance(nodes[0], Assign)
        assert nodes[0].target == "x"
        assert isinstance(nodes[0].value, Param)

    def test_sub_assign(self):
        func = _parse_func("""
            def trans(self, delta):
                self.x -= delta
        """)
        nodes = lower_transition(func, ["delta"])
        assert nodes[0].value.op == "-"

    def test_multiple_mutations(self):
        func = _parse_func("""
            def trans(self, v):
                require(self.x + v <= 100)
                self.x += v
                self.y += 1
        """)
        nodes = lower_transition(func, ["v"])
        assert len(nodes) == 3
        assert isinstance(nodes[0], Require)
        assert isinstance(nodes[1], Assign)
        assert isinstance(nodes[2], Assign)

    def test_param_reference(self):
        func = _parse_func("""
            def trans(self, delta):
                self.x += delta
        """)
        nodes = lower_transition(func, ["delta"])
        assign = nodes[0]
        assert isinstance(assign.value.right, Param)
        assert assign.value.right.name == "delta"


class TestUnsupportedConstructs:
    def test_for_loop(self):
        func = _parse_func("""
            def inv(self):
                for i in range(10):
                    pass
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="for loop"):
            lower_invariant(func)

    def test_while_loop(self):
        func = _parse_func("""
            def inv(self):
                while True:
                    pass
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="while loop"):
            lower_invariant(func)

    def test_print_call(self):
        func = _parse_func("""
            def trans(self):
                print("hello")
        """)
        with pytest.raises(UnsupportedConstructError, match="function call"):
            lower_transition(func, [])

    def test_list_comprehension(self):
        func = _parse_func("""
            def inv(self):
                return [i for i in range(10)]
        """)
        with pytest.raises(UnsupportedConstructError, match="list comprehension"):
            lower_invariant(func)

    def test_import(self):
        func = _parse_func("""
            def inv(self):
                import os
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="import"):
            lower_invariant(func)

    def test_try_except(self):
        func = _parse_func("""
            def inv(self):
                try:
                    pass
                except:
                    pass
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="try/except"):
            lower_invariant(func)

    def test_non_self_attribute(self):
        func = _parse_func("""
            def inv(self):
                return other.x >= 0
        """)
        with pytest.raises(UnsupportedConstructError, match="only supported on 'self'"):
            lower_invariant(func)

    def test_nested_function(self):
        func = _parse_func("""
            def inv(self):
                def helper():
                    pass
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="nested function"):
            lower_invariant(func)

    def test_walrus_operator(self):
        func = _parse_func("""
            def inv(self):
                return (x := self.x) >= 0
        """)
        with pytest.raises(UnsupportedConstructError, match="walrus"):
            lower_invariant(func)

    def test_function_call_in_expr(self):
        func = _parse_func("""
            def inv(self):
                return len(self.x) >= 0
        """)
        with pytest.raises(UnsupportedConstructError, match="Function call"):
            lower_invariant(func)
