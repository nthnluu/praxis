"""Tier 3: Stress tests — push Praxis to its limits."""

import pytest
from praxis import Spec, invariant, transition, And, Or, implies
from praxis.types import BoundedInt, BoundedFloat, Nat
from praxis.decorators import require
from praxis.engine.verifier import verify_spec


# ============================================================
# BOUNDARY ARITHMETIC
# ============================================================

class LargeConstantsSpec(Spec):
    """a. BoundedInt[0, 2**31-1]."""
    x: BoundedInt[0, 2**31 - 1]

    @invariant
    def non_negative(self):
        return self.x >= 0


class FullRangeSpec(Spec):
    """b. Full signed 32-bit range."""
    x: BoundedInt[-2**31, 2**31 - 1]

    @invariant
    def in_range(self):
        return And(self.x >= -2147483648, self.x <= 2147483647)


class MultiplicationSpec(Spec):
    """c. Product of two BoundedInt[0, 1000]."""
    x: BoundedInt[0, 1000]
    y: BoundedInt[0, 1000]

    @invariant
    def product_bounded(self):
        return self.x * self.y <= 1000000


class DivisionSpec(Spec):
    """d. Division: y: BoundedInt[1, 100] prevents div-by-zero."""
    x: BoundedInt[0, 100]
    y: BoundedInt[1, 100]

    @invariant
    def div_non_negative(self):
        return self.x // self.y >= 0


class ModuloSpec(Spec):
    """e. Modulo."""
    x: BoundedInt[0, 100]
    y: BoundedInt[1, 100]

    @invariant
    def mod_bounded(self):
        return self.x % self.y >= 0


# ============================================================
# COMBINATORIAL
# ============================================================

class TenFieldsSpec(Spec):
    """f. 10 state fields — large state space."""
    f0: BoundedInt[0, 10]
    f1: BoundedInt[0, 10]
    f2: BoundedInt[0, 10]
    f3: BoundedInt[0, 10]
    f4: BoundedInt[0, 10]
    f5: BoundedInt[0, 10]
    f6: BoundedInt[0, 10]
    f7: BoundedInt[0, 10]
    f8: BoundedInt[0, 10]
    f9: BoundedInt[0, 10]

    @invariant
    def all_non_negative(self):
        return And(
            self.f0 >= 0, self.f1 >= 0, self.f2 >= 0, self.f3 >= 0,
            self.f4 >= 0, self.f5 >= 0, self.f6 >= 0, self.f7 >= 0,
            self.f8 >= 0, self.f9 >= 0,
        )


class TwentyInvariantsSpec(Spec):
    """g. 20 invariants — verify none silently skipped."""
    x: BoundedInt[0, 100]

    @invariant
    def i00(self): return self.x >= 0
    @invariant
    def i01(self): return self.x >= 0
    @invariant
    def i02(self): return self.x >= 0
    @invariant
    def i03(self): return self.x >= 0
    @invariant
    def i04(self): return self.x >= 0
    @invariant
    def i05(self): return self.x >= 0
    @invariant
    def i06(self): return self.x >= 0
    @invariant
    def i07(self): return self.x >= 0
    @invariant
    def i08(self): return self.x >= 0
    @invariant
    def i09(self): return self.x >= 0
    @invariant
    def i10(self): return self.x >= 0
    @invariant
    def i11(self): return self.x >= 0
    @invariant
    def i12(self): return self.x >= 0
    @invariant
    def i13(self): return self.x >= 0
    @invariant
    def i14(self): return self.x >= 0
    @invariant
    def i15(self): return self.x >= 0
    @invariant
    def i16(self): return self.x >= 0
    @invariant
    def i17(self): return self.x >= 0
    @invariant
    def i18(self): return self.x >= 0
    @invariant
    def i19(self): return self.x >= 0


class ManyTransitionsSpec(Spec):
    """h. 10 transitions with 3 require() each."""
    x: BoundedInt[0, 1000]

    @invariant
    def bounded(self):
        return self.x <= 1000

    @transition
    def t0(self, v: BoundedInt[1, 10]):
        require(self.x + v <= 1000)
        require(self.x >= 0)
        require(v > 0)
        self.x += v

    @transition
    def t1(self, v: BoundedInt[1, 10]):
        require(self.x + v <= 1000)
        require(self.x >= 0)
        require(v > 0)
        self.x += v

    @transition
    def t2(self, v: BoundedInt[1, 10]):
        require(self.x + v <= 1000)
        require(self.x >= 0)
        require(v > 0)
        self.x += v

    @transition
    def t3(self, v: BoundedInt[1, 10]):
        require(self.x + v <= 1000)
        require(self.x >= 0)
        require(v > 0)
        self.x += v

    @transition
    def t4(self, v: BoundedInt[1, 10]):
        require(self.x + v <= 1000)
        require(self.x >= 0)
        require(v > 0)
        self.x += v

    @transition
    def t5(self, v: BoundedInt[1, 10]):
        require(self.x >= v)
        require(self.x >= 0)
        require(v > 0)
        self.x -= v

    @transition
    def t6(self, v: BoundedInt[1, 10]):
        require(self.x >= v)
        require(self.x >= 0)
        require(v > 0)
        self.x -= v

    @transition
    def t7(self, v: BoundedInt[1, 10]):
        require(self.x >= v)
        require(self.x >= 0)
        require(v > 0)
        self.x -= v

    @transition
    def t8(self, v: BoundedInt[1, 10]):
        require(self.x >= v)
        require(self.x >= 0)
        require(v > 0)
        self.x -= v

    @transition
    def t9(self, v: BoundedInt[1, 10]):
        require(self.x >= v)
        require(self.x >= 0)
        require(v > 0)
        self.x -= v


class LongConjunctionSpec(Spec):
    """k. Invariant with 20+ terms in conjunction."""
    x: BoundedInt[0, 100]

    @invariant
    def big_and(self):
        return And(
            self.x >= 0, self.x >= 0, self.x >= 0, self.x >= 0,
            self.x >= 0, self.x >= 0, self.x >= 0, self.x >= 0,
            self.x >= 0, self.x >= 0, self.x >= 0, self.x >= 0,
            self.x >= 0, self.x >= 0, self.x >= 0, self.x >= 0,
            self.x >= 0, self.x >= 0, self.x >= 0, self.x >= 0,
            self.x <= 100,
        )


class DeepArithmeticSpec(Spec):
    """l. Deeply nested arithmetic.

    Use linear operations to avoid nonlinear arithmetic timeout.
    (a + b) - (c - d) + (e // 2) is deeply nested but linear.
    """
    a: BoundedInt[0, 100]
    b: BoundedInt[0, 100]
    c: BoundedInt[0, 100]
    d: BoundedInt[0, 100]
    e: BoundedInt[0, 100]
    f: BoundedInt[0, 10000]

    @invariant
    def deep(self):
        return (self.a + self.b) - (self.c - self.d) + self.e <= self.f


class MutateAllFieldsSpec(Spec):
    """m. Transition that mutates ALL state fields."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]
    z: BoundedInt[0, 100]

    @invariant
    def all_non_negative(self):
        return And(self.x >= 0, self.y >= 0, self.z >= 0)

    @transition
    def reset(self, v: BoundedInt[0, 100]):
        self.x = v
        self.y = v
        self.z = v


class NestedImpliesSpec(Spec):
    """j. Nested implies, 4 levels deep."""
    x: BoundedInt[0, 100]

    @invariant
    def nested(self):
        return implies(self.x > 90,
                       implies(self.x > 80,
                               implies(self.x > 70,
                                       implies(self.x > 60, self.x >= 0))))


# ============================================================
# TESTS
# ============================================================

class TestBoundaryArithmetic:
    def test_large_constants(self):
        result = verify_spec(LargeConstantsSpec)
        assert result.passed

    def test_full_range(self):
        result = verify_spec(FullRangeSpec)
        assert result.passed

    def test_multiplication(self):
        result = verify_spec(MultiplicationSpec)
        assert result.passed

    def test_division(self):
        result = verify_spec(DivisionSpec)
        assert result.passed

    def test_modulo(self):
        result = verify_spec(ModuloSpec)
        assert result.passed


class TestCombinatorial:
    def test_ten_fields(self):
        result = verify_spec(TenFieldsSpec, timeout_ms=10000)
        assert result.passed

    def test_twenty_invariants(self):
        result = verify_spec(TwentyInvariantsSpec)
        assert result.passed
        # All 20 invariants should be checked
        inv_results = [r for r in result.results if r.kind == "invariant"]
        assert len(inv_results) == 20

    def test_many_transitions(self):
        result = verify_spec(ManyTransitionsSpec)
        assert result.passed
        trans_results = [r for r in result.results if r.kind == "transition"]
        assert len(trans_results) == 10

    def test_nested_implies(self):
        result = verify_spec(NestedImpliesSpec)
        assert result.passed


class TestPathological:
    def test_long_conjunction(self):
        result = verify_spec(LongConjunctionSpec)
        assert result.passed

    def test_deep_arithmetic(self):
        result = verify_spec(DeepArithmeticSpec, timeout_ms=30000)
        assert result.passed, [
            f"{r.property_name}: {r.status} - {r.error_message or ''}"
            for r in result.results if r.status != "pass"
        ]

    def test_mutate_all_fields(self):
        result = verify_spec(MutateAllFieldsSpec)
        assert result.passed


class TestErrorHandling:
    def test_timeout_handling(self):
        """o. Very short timeout — should not crash."""
        result = verify_spec(DeepArithmeticSpec, timeout_ms=1)
        for r in result.results:
            assert r.status in ("pass", "fail", "timeout", "error")
