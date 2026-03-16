"""Tests for praxis.compiler.emitter."""

import z3
from praxis.compiler.ir import (
    Var, Param, Const, BinOp, UnaryOp, Compare, BoolOp, IfExpr,
    Require, Assign, Return, PrimedVar,
)
from praxis.compiler.emitter import EmitContext, emit
from praxis.types import BoundedInt, BoundedFloat, Bool


def _make_ctx():
    ctx = EmitContext()
    ctx.add_state_var("x", BoundedInt[0, 100])
    ctx.add_state_var("y", BoundedInt[0, 100])
    ctx.add_primed_var("x", BoundedInt[0, 100])
    ctx.add_param("delta", BoundedInt[-10, 10])
    return ctx


class TestEmitBasic:
    def test_var(self):
        ctx = _make_ctx()
        result = emit(Var("x"), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_primed_var(self):
        ctx = _make_ctx()
        result = emit(PrimedVar("x"), ctx)
        assert isinstance(result, z3.ArithRef)
        assert "x'" in str(result)

    def test_param(self):
        ctx = _make_ctx()
        result = emit(Param("delta"), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_const_int(self):
        ctx = _make_ctx()
        result = emit(Const(42), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_const_bool(self):
        ctx = _make_ctx()
        result = emit(Const(True), ctx)
        assert isinstance(result, z3.BoolRef)


class TestEmitOps:
    def test_binop_add(self):
        ctx = _make_ctx()
        result = emit(BinOp("+", Var("x"), Var("y")), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_binop_sub(self):
        ctx = _make_ctx()
        result = emit(BinOp("-", Var("x"), Const(1)), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_binop_mul(self):
        ctx = _make_ctx()
        result = emit(BinOp("*", Var("x"), Const(2)), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_binop_floordiv(self):
        ctx = _make_ctx()
        result = emit(BinOp("//", Var("x"), Const(2)), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_floordiv_positive_divisor_matches_python(self):
        """Floor division with positive divisor matches Python semantics."""
        from praxis.types import BoundedInt as BI
        ctx = EmitContext()
        ctx.add_state_var("a", BI[-100, 100])
        ctx.add_state_var("b", BI[1, 100])  # positive divisor (standard usage)
        expr = emit(BinOp("//", Var("a"), Var("b")), ctx)
        # -7 // 2 == -4 in both Python and Z3 (floor division for positive divisor)
        s = z3.Solver()
        s.add(ctx.vars["a"] == -7, ctx.vars["b"] == 2)
        s.add(expr == -4)
        assert s.check() == z3.sat
        # 7 // 2 == 3
        s2 = z3.Solver()
        s2.add(ctx.vars["a"] == 7, ctx.vars["b"] == 2)
        s2.add(expr == 3)
        assert s2.check() == z3.sat

    def test_binop_mod(self):
        ctx = _make_ctx()
        result = emit(BinOp("%", Var("x"), Const(3)), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_unary_neg(self):
        ctx = _make_ctx()
        result = emit(UnaryOp("-", Var("x")), ctx)
        assert isinstance(result, z3.ArithRef)

    def test_unary_not(self):
        ctx = EmitContext()
        ctx.add_state_var("flag", Bool)
        result = emit(UnaryOp("not", Var("flag")), ctx)
        assert isinstance(result, z3.BoolRef)


class TestEmitComparisons:
    def test_all_ops(self):
        ctx = _make_ctx()
        for op in ["<", "<=", ">", ">=", "==", "!="]:
            result = emit(Compare(op, Var("x"), Const(50)), ctx)
            assert isinstance(result, z3.BoolRef)


class TestEmitBoolOps:
    def test_and(self):
        ctx = _make_ctx()
        result = emit(
            BoolOp("and", (Compare(">=", Var("x"), Const(0)),
                           Compare("<=", Var("x"), Const(100)))),
            ctx,
        )
        assert isinstance(result, z3.BoolRef)

    def test_or(self):
        ctx = _make_ctx()
        result = emit(
            BoolOp("or", (Compare("==", Var("x"), Const(0)),
                          Compare("==", Var("x"), Const(100)))),
            ctx,
        )
        assert isinstance(result, z3.BoolRef)


class TestEmitIfExpr:
    def test_ternary(self):
        ctx = _make_ctx()
        result = emit(
            IfExpr(
                Compare(">", Var("y"), Const(0)),
                Var("x"),
                Var("y"),
            ),
            ctx,
        )
        assert isinstance(result, z3.ArithRef)


class TestEmitReturn:
    def test_return(self):
        ctx = _make_ctx()
        result = emit(Return(Compare(">=", Var("x"), Const(0))), ctx)
        assert isinstance(result, z3.BoolRef)


class TestEmitConstraints:
    def test_bounded_int_restricts_domain(self):
        """BoundedInt[0, 100] should reject x == 101."""
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        s = z3.Solver()
        s.add(*ctx.constraints)
        s.add(ctx.vars["x"] == 101)
        assert s.check() == z3.unsat

    def test_bounded_int_allows_valid(self):
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        s = z3.Solver()
        s.add(*ctx.constraints)
        s.add(ctx.vars["x"] == 50)
        assert s.check() == z3.sat

    def test_full_pipeline_sat(self):
        """Emit an invariant and verify Z3 can find a satisfying model."""
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        # invariant: x >= 0
        inv_ir = Return(Compare(">=", Var("x"), Const(0)))
        inv_z3 = emit(inv_ir, ctx)
        s = z3.Solver()
        s.add(*ctx.constraints)
        s.add(z3.Not(inv_z3))
        # Should be UNSAT because x >= 0 is guaranteed by bounds
        assert s.check() == z3.unsat

    def test_full_pipeline_unsat(self):
        """An invariant that's too tight — Z3 should find counterexample."""
        ctx = EmitContext()
        ctx.add_state_var("x", BoundedInt[0, 100])
        # invariant: x > 100 — impossible given bounds
        inv_ir = Return(Compare(">", Var("x"), Const(100)))
        inv_z3 = emit(inv_ir, ctx)
        s = z3.Solver()
        s.add(*ctx.constraints)
        s.add(z3.Not(inv_z3))
        # Should be SAT — there exist values where x <= 100
        assert s.check() == z3.sat
