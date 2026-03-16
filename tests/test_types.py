"""Tests for praxis.types — Z3 sort mapping and bounds."""

import pytest
import z3

from praxis.types import BoundedInt, BoundedFloat, Bool, Nat, is_praxis_type


class TestBoundedInt:
    def test_basic_z3(self):
        T = BoundedInt[0, 100]
        var, constraints = T.to_z3("x")
        assert isinstance(var, z3.ArithRef)
        assert len(constraints) == 2

    def test_constraints_restrict_domain(self):
        T = BoundedInt[0, 100]
        var, constraints = T.to_z3("x")
        s = z3.Solver()
        s.add(*constraints)
        s.add(var == 50)
        assert s.check() == z3.sat

        s2 = z3.Solver()
        s2.add(*constraints)
        s2.add(var == 101)
        assert s2.check() == z3.unsat

        s3 = z3.Solver()
        s3.add(*constraints)
        s3.add(var == -1)
        assert s3.check() == z3.unsat

    def test_single_value_domain(self):
        T = BoundedInt[0, 0]
        var, constraints = T.to_z3("x")
        s = z3.Solver()
        s.add(*constraints)
        assert s.check() == z3.sat
        assert s.model()[var].as_long() == 0

    def test_negative_bounds(self):
        T = BoundedInt[-100, 100]
        var, constraints = T.to_z3("x")
        s = z3.Solver()
        s.add(*constraints, var == -50)
        assert s.check() == z3.sat

    def test_all_negative_domain(self):
        T = BoundedInt[-100, -1]
        var, constraints = T.to_z3("x")
        s = z3.Solver()
        s.add(*constraints, var == 0)
        assert s.check() == z3.unsat

    def test_full_int32_range(self):
        T = BoundedInt[-2**31, 2**31 - 1]
        var, constraints = T.to_z3("x")
        s = z3.Solver()
        s.add(*constraints)
        assert s.check() == z3.sat

    def test_metadata_preserved(self):
        T = BoundedInt[10, 20]
        assert T._lo == 10
        assert T._hi == 20
        assert T._praxis_type == "BoundedInt"

    def test_invalid_lo_gt_hi(self):
        with pytest.raises(ValueError, match="lower bound.*upper bound"):
            BoundedInt[5, 3]

    def test_invalid_non_numeric(self):
        with pytest.raises(TypeError, match="integers"):
            BoundedInt["a", "b"]

    def test_is_praxis_type(self):
        assert is_praxis_type(BoundedInt[0, 100])
        assert is_praxis_type(BoundedInt)


class TestNat:
    def test_bounds(self):
        assert Nat._lo == 0
        assert Nat._hi == 2**63 - 1

    def test_rejects_negative(self):
        var, constraints = Nat.to_z3("n")
        s = z3.Solver()
        s.add(*constraints, var == -1)
        assert s.check() == z3.unsat


class TestInt:
    def test_bounds(self):
        from praxis.types import Int
        assert Int._lo == -2**63
        assert Int._hi == 2**63 - 1

    def test_allows_negative(self):
        from praxis.types import Int
        var, constraints = Int.to_z3("x")
        s = z3.Solver()
        s.add(*constraints, var == -1000)
        assert s.check() == z3.sat


class TestPosInt:
    def test_bounds(self):
        from praxis.types import PosInt
        assert PosInt._lo == 1
        assert PosInt._hi == 2**63 - 1

    def test_rejects_zero(self):
        from praxis.types import PosInt
        var, constraints = PosInt.to_z3("x")
        s = z3.Solver()
        s.add(*constraints, var == 0)
        assert s.check() == z3.unsat

    def test_allows_one(self):
        from praxis.types import PosInt
        var, constraints = PosInt.to_z3("x")
        s = z3.Solver()
        s.add(*constraints, var == 1)
        assert s.check() == z3.sat


class TestBoundedFloat:
    def test_basic_z3(self):
        T = BoundedFloat[0.0, 1.0]
        var, constraints = T.to_z3("f")
        assert isinstance(var, z3.ArithRef)
        assert len(constraints) == 2

    def test_constraints_restrict_domain(self):
        T = BoundedFloat[0.0, 1.0]
        var, constraints = T.to_z3("f")
        s = z3.Solver()
        s.add(*constraints, var == z3.RealVal(0.5))
        assert s.check() == z3.sat
        s2 = z3.Solver()
        s2.add(*constraints, var == z3.RealVal(1.5))
        assert s2.check() == z3.unsat

    def test_single_value_domain(self):
        T = BoundedFloat[0.0, 0.0]
        var, constraints = T.to_z3("f")
        s = z3.Solver()
        s.add(*constraints)
        assert s.check() == z3.sat

    def test_metadata(self):
        T = BoundedFloat[1.5, 3.5]
        assert T._lo == 1.5
        assert T._hi == 3.5

    def test_invalid_lo_gt_hi(self):
        with pytest.raises(ValueError):
            BoundedFloat[5.0, 3.0]

    def test_invalid_non_numeric(self):
        with pytest.raises(TypeError):
            BoundedFloat["a", "b"]

    def test_int_bounds_accepted(self):
        T = BoundedFloat[0, 100]
        var, constraints = T.to_z3("f")
        assert isinstance(var, z3.ArithRef)


class TestBool:
    def test_z3(self):
        var, constraints = Bool.to_z3("b")
        assert isinstance(var, z3.BoolRef)
        assert constraints == []

    def test_is_praxis_type(self):
        assert is_praxis_type(Bool)
