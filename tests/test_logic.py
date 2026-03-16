"""Tests for praxis.logic — logical combinators."""

import z3

from praxis.logic import And, Or, Not, implies, forall, exists


class TestAnd:
    def test_python_bools(self):
        assert And(True, True) is True
        assert not And(True, False)

    def test_z3(self):
        a, b = z3.Bool("a"), z3.Bool("b")
        assert isinstance(And(a, b), z3.BoolRef)

    def test_mixed(self):
        assert isinstance(And(z3.Bool("a"), True), z3.BoolRef)

    def test_empty(self):
        assert And() is True


class TestOr:
    def test_python_bools(self):
        assert Or(False, True)
        assert not Or(False, False)

    def test_z3(self):
        assert isinstance(Or(z3.Bool("a"), z3.Bool("b")), z3.BoolRef)

    def test_empty(self):
        assert Or() is False


class TestNot:
    def test_python(self):
        assert Not(True) is False
        assert Not(False) is True

    def test_z3(self):
        assert isinstance(Not(z3.Bool("a")), z3.BoolRef)


class TestImplies:
    def test_false_antecedent(self):
        assert implies(False, False) is True
        assert implies(False, True) is True

    def test_true_antecedent(self):
        assert implies(True, True) is True
        assert implies(True, False) is False

    def test_z3(self):
        a, b = z3.Bool("a"), z3.Bool("b")
        assert isinstance(implies(a, b), z3.BoolRef)

    def test_z3_false_implies_anything(self):
        """implies(False, b) should always be true."""
        b = z3.Bool("b")
        result = implies(False, b)
        s = z3.Solver()
        s.add(z3.Not(result))
        assert s.check() == z3.unsat


class TestForall:
    def test_empty_range_vacuous_truth(self):
        assert forall(range(0), lambda i: False) is True

    def test_unrolled_small(self):
        x = z3.Int("x")
        result = forall(range(5), lambda i: x + i >= 0)
        assert isinstance(result, z3.BoolRef)

    def test_unrolled_at_threshold(self):
        x = z3.Int("x")
        result = forall(range(50), lambda i: x + i >= 0)
        assert isinstance(result, z3.BoolRef)

    def test_quantified_above_threshold(self):
        x = z3.Int("x")
        result = forall(range(51), lambda i: x + i >= 0)
        assert isinstance(result, z3.BoolRef)

    def test_python_all_true(self):
        assert forall(range(5), lambda i: True) is True

    def test_python_some_false(self):
        assert forall(range(5), lambda i: i < 3) is False


class TestExists:
    def test_empty_range(self):
        assert exists(range(0), lambda i: True) is False

    def test_unrolled(self):
        x = z3.Int("x")
        result = exists(range(5), lambda i: x == i)
        assert isinstance(result, z3.BoolRef)

    def test_python_found(self):
        assert exists(range(5), lambda i: i == 3) is True

    def test_python_not_found(self):
        assert exists(range(5), lambda i: i == 10) is False


class TestNested:
    def test_forall_exists(self):
        x = z3.Int("x")
        result = forall(range(5), lambda i: exists(range(5), lambda j: x + i == j))
        assert isinstance(result, z3.BoolRef)
