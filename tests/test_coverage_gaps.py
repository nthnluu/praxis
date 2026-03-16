"""Tests for previously uncovered code paths found during coverage audit."""

import ast
import textwrap

import pytest
import z3

from praxis import Spec, invariant, transition
from praxis.types import BoundedInt
from praxis.decorators import require
from praxis.compiler.lowering import lower_invariant, lower_transition, UnsupportedConstructError
from praxis.compiler.emitter import EmitContext, emit
from praxis.compiler.ir import (
    Var, Const, BinOp, UnaryOp, Compare, BoolOp, IfExpr,
    Require, Assign, Return, Param, IRNode,
)
from praxis.engine.verifier import verify_spec
from praxis.engine.counterexample import Counterexample, _z3_val_to_python
from praxis.engine.fallback import generate_strategy, fuzz_invariant


def _parse_func(source: str) -> ast.FunctionDef:
    return ast.parse(textwrap.dedent(source)).body[0]


class TestLoweringErrorPaths:
    def test_require_zero_args(self):
        func = _parse_func("""
            def trans(self):
                require()
        """)
        with pytest.raises(UnsupportedConstructError, match="exactly one argument"):
            lower_transition(func, [])

    def test_require_two_args(self):
        func = _parse_func("""
            def trans(self):
                require(self.x > 0, self.y > 0)
        """)
        with pytest.raises(UnsupportedConstructError, match="exactly one argument"):
            lower_transition(func, [])

    def test_not_wrong_arg_count(self):
        func = _parse_func("""
            def inv(self):
                return Not(self.x > 0, self.y > 0)
        """)
        with pytest.raises(UnsupportedConstructError, match="exactly one argument"):
            lower_invariant(func)

    def test_implies_one_arg(self):
        func = _parse_func("""
            def inv(self):
                return implies(self.x > 0)
        """)
        with pytest.raises(UnsupportedConstructError, match="exactly two arguments"):
            lower_invariant(func)

    def test_implies_three_args(self):
        func = _parse_func("""
            def inv(self):
                return implies(self.x > 0, self.y > 0, self.z > 0)
        """)
        with pytest.raises(UnsupportedConstructError, match="exactly two arguments"):
            lower_invariant(func)

    def test_invariant_missing_return(self):
        func = _parse_func("""
            def inv(self):
                pass
        """)
        with pytest.raises(UnsupportedConstructError):
            lower_invariant(func)

    def test_and_single_arg(self):
        func = _parse_func("""
            def inv(self):
                return And(self.x > 0)
        """)
        result = lower_invariant(func)
        assert isinstance(result, Return)
        assert isinstance(result.value, BoolOp)


class TestEmitterErrorPaths:
    def test_const_string_unsupported(self):
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        with pytest.raises(TypeError, match="Unsupported constant type"):
            emit(Const("hello"), ctx)

    def test_const_none_unsupported(self):
        ctx = EmitContext()
        with pytest.raises(TypeError, match="Unsupported constant type"):
            emit(Const(None), ctx)

    def test_binop_unknown_operator(self):
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        with pytest.raises(ValueError, match="Unknown binary operator"):
            emit(BinOp("**", Var("x"), Const(2)), ctx)

    def test_unaryop_unknown_operator(self):
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        with pytest.raises(ValueError, match="Unknown unary operator"):
            emit(UnaryOp("~", Var("x")), ctx)

    def test_compare_unknown_operator(self):
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        with pytest.raises(ValueError, match="Unknown comparison operator"):
            emit(Compare("<>", Var("x"), Const(50)), ctx)

    def test_boolop_unknown_operator(self):
        ctx = EmitContext()
        with pytest.raises(ValueError, match="Unknown boolean operator"):
            emit(BoolOp("xor", (Const(True), Const(False))), ctx)

    def test_unknown_ir_node_type(self):
        ctx = EmitContext()
        with pytest.raises(TypeError, match="Cannot emit IR node type"):
            emit(type("FakeNode", (IRNode,), {})(), ctx)

    def test_implies_in_emitter(self):
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        result = emit(
            BoolOp("implies", (Compare(">=", Var("x"), Const(50)), Compare(">=", Var("x"), Const(0)))),
            ctx,
        )
        assert isinstance(result, z3.BoolRef)


class TestCounterexampleEdgeCases:
    def test_rational_unit_denominator(self):
        """Rational value with denominator 1 should return int."""
        val = z3.RatVal(42, 1)
        assert _z3_val_to_python(val) == 42
        assert isinstance(_z3_val_to_python(val), int)

    def test_rational_non_unit_denominator(self):
        val = z3.RatVal(1, 3)
        result = _z3_val_to_python(val)
        assert isinstance(result, float)

    def test_counterexample_no_transition(self):
        ce = Counterexample(
            spec_name="T", property_name="inv",
            kind="invariant_inconsistency",
            before={"x": 5},
        )
        text = ce.to_human()
        assert "UNSATISFIABLE" in text
        assert "After transition" not in text

    def test_counterexample_with_message(self):
        ce = Counterexample(
            spec_name="T", property_name="inv",
            kind="invariant_violation",
            transition="update",
            before={"x": 5},
            message="CRITICAL: resource overcommit",
        )
        text = ce.to_human()
        assert "CRITICAL: resource overcommit" in text
        j = ce.to_json()
        assert j["message"] == "CRITICAL: resource overcommit"


class TestFallbackEdgeCases:
    def test_unknown_praxis_type(self):
        class UnknownType:
            _praxis_type = "CustomThing"
        with pytest.raises(TypeError, match="Cannot generate strategy"):
            generate_strategy(UnknownType)

    def test_generate_strategy_bool(self):
        from praxis.types import Bool
        st = generate_strategy(Bool)
        assert st is not None

    def test_generate_strategy_bounded_float(self):
        from praxis.types import BoundedFloat
        st = generate_strategy(BoundedFloat[0.0, 1.0])
        assert st is not None


class TestVerifierEdgeCases:
    def test_spec_no_invariants(self):
        class NoInvSpec(Spec):
            x: BoundedInt[0, 100]

            @transition
            def inc(self, delta: BoundedInt[1, 10]):
                require(self.x + delta <= 100)
                self.x += delta

        result = verify_spec(NoInvSpec)
        inv_results = [r for r in result.results if r.kind == "invariant"]
        assert len(inv_results) == 0
        # Transition should still be checked (trivially passes with no invariants)
