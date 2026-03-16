"""Tests for user-facing error messages — every common mistake should produce helpful output."""

import ast
import textwrap

import pytest

from praxis import Spec, invariant, transition
from praxis.types import BoundedInt
from praxis.decorators import require
from praxis.compiler.lowering import lower_invariant, lower_transition, UnsupportedConstructError
from praxis.compiler.emitter import EmitContext, emit
from praxis.compiler.ir import Var, Const, BinOp, Compare, Return


def _parse_func(source: str) -> ast.FunctionDef:
    source = textwrap.dedent(source)
    tree = ast.parse(source)
    return tree.body[0]


class TestLoweringErrors:
    """Common mistakes in spec method bodies produce helpful errors."""

    def test_bare_variable_suggests_self(self):
        """Using 'x' instead of 'self.x' should suggest the fix."""
        func = _parse_func("""
            def inv(self):
                return x >= 0
        """)
        with pytest.raises(UnsupportedConstructError, match="self.field"):
            lower_invariant(func)

    def test_for_loop_suggests_forall(self):
        func = _parse_func("""
            def inv(self):
                for i in range(10):
                    pass
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="forall"):
            lower_invariant(func)

    def test_function_call_names_function(self):
        func = _parse_func("""
            def inv(self):
                return len(self.x) >= 0
        """)
        with pytest.raises(UnsupportedConstructError, match="Function call"):
            lower_invariant(func)

    def test_while_loop_rejected(self):
        func = _parse_func("""
            def inv(self):
                while True:
                    pass
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="while"):
            lower_invariant(func)

    def test_import_rejected(self):
        func = _parse_func("""
            def inv(self):
                import os
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="import"):
            lower_invariant(func)

    def test_try_except_rejected(self):
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

    def test_non_self_attribute_names_object(self):
        func = _parse_func("""
            def inv(self):
                return other.x >= 0
        """)
        with pytest.raises(UnsupportedConstructError, match="only supported on 'self'"):
            lower_invariant(func)

    def test_nested_function_rejected(self):
        func = _parse_func("""
            def inv(self):
                def helper():
                    pass
                return True
        """)
        with pytest.raises(UnsupportedConstructError, match="nested function"):
            lower_invariant(func)

    def test_list_comprehension_suggests_forall(self):
        func = _parse_func("""
            def inv(self):
                return [i for i in range(10)]
        """)
        with pytest.raises(UnsupportedConstructError, match="list comprehension"):
            lower_invariant(func)

    def test_walrus_operator_rejected(self):
        func = _parse_func("""
            def inv(self):
                return (x := self.x) >= 0
        """)
        with pytest.raises(UnsupportedConstructError, match="walrus"):
            lower_invariant(func)

    def test_print_in_transition_rejected(self):
        func = _parse_func("""
            def trans(self):
                print("hello")
        """)
        with pytest.raises(UnsupportedConstructError, match="function call"):
            lower_transition(func, [])

    def test_augassign_on_non_self_rejected(self):
        func = _parse_func("""
            def trans(self, x):
                x += 1
        """)
        with pytest.raises(UnsupportedConstructError, match="self.field"):
            lower_transition(func, ["x"])


class TestEmitterErrors:
    """Emitter rejects unknown variables with clear messages."""

    def test_unknown_state_var(self):
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        with pytest.raises(KeyError, match="Unknown state variable: y"):
            emit(Var("y"), ctx)

    def test_unknown_param(self):
        ctx = EmitContext()
        from praxis.compiler.ir import Param
        with pytest.raises(KeyError, match="Unknown parameter: delta"):
            emit(Param("delta"), ctx)


class TestSpecErrors:
    """Spec construction errors are clear."""

    def test_unparameterized_bounded_int(self):
        with pytest.raises(TypeError, match="unparameterized"):
            BoundedInt.to_z3("x")

    def test_bounds_reversed(self):
        with pytest.raises(ValueError, match="lower bound.*upper bound"):
            BoundedInt[100, 0]

    def test_non_numeric_bounds(self):
        with pytest.raises(TypeError, match="integers"):
            BoundedInt["a", "b"]
