"""Tests for @initial decorator and induction base case verification."""

from praxis import Spec, initial, invariant, transition, And
from praxis.types import BoundedInt
from praxis.engine.verifier import verify_spec


class ValidInitialSpec(Spec):
    """Initial state satisfies the invariant."""
    account_a: BoundedInt[0, 100_000]
    account_b: BoundedInt[0, 100_000]
    total_deposited: BoundedInt[0, 200_000]

    @initial
    def start_empty(self):
        return And(self.account_a == 0, self.account_b == 0, self.total_deposited == 0)

    @invariant
    def conservation(self):
        return self.account_a + self.account_b == self.total_deposited


class InvalidInitialSpec(Spec):
    """Initial state violates the invariant — base case fails."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @initial
    def bad_start(self):
        return And(self.x == 10, self.y == 0)

    @invariant
    def must_be_equal(self):
        return self.x == self.y


class NoInitialSpec(Spec):
    """Spec without @initial — should skip initial checks (backward compatible)."""
    x: BoundedInt[0, 100]

    @invariant
    def non_negative(self):
        return self.x >= 0


class MultipleInitialsSpec(Spec):
    """Multiple @initial predicates — all must satisfy invariants."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @initial
    def start_zeros(self):
        return And(self.x == 0, self.y == 0)

    @initial
    def start_equal(self):
        return And(self.x == 50, self.y == 50)

    @invariant
    def sum_bounded(self):
        return self.x + self.y <= 100


class MultipleInitialsOneFailsSpec(Spec):
    """One of multiple @initial predicates violates an invariant."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @initial
    def start_zeros(self):
        return And(self.x == 0, self.y == 0)

    @initial
    def start_too_big(self):
        return And(self.x == 100, self.y == 100)

    @invariant
    def sum_bounded(self):
        return self.x + self.y <= 100


class TestValidInitial:
    def test_initial_satisfies_invariants(self):
        result = verify_spec(ValidInitialSpec)
        initial_results = [r for r in result.results if r.kind == "initial"]
        assert len(initial_results) == 1
        assert initial_results[0].status == "pass"
        assert initial_results[0].property_name == "start_empty"

    def test_overall_passes(self):
        result = verify_spec(ValidInitialSpec)
        assert result.passed


class TestInvalidInitial:
    def test_initial_violates_invariant(self):
        result = verify_spec(InvalidInitialSpec)
        initial_results = [r for r in result.results if r.kind == "initial"]
        assert len(initial_results) == 1
        assert initial_results[0].status == "fail"
        assert initial_results[0].counterexample is not None

    def test_counterexample_shows_violating_state(self):
        result = verify_spec(InvalidInitialSpec)
        initial_results = [r for r in result.results if r.kind == "initial"]
        ce = initial_results[0].counterexample
        # The initial state x=10, y=0 violates x == y
        assert ce.before["x"] == 10
        assert ce.before["y"] == 0
        assert ce.kind == "initial_violation"

    def test_overall_fails(self):
        result = verify_spec(InvalidInitialSpec)
        assert not result.passed


class TestNoInitial:
    def test_no_initial_checks_generated(self):
        result = verify_spec(NoInitialSpec)
        initial_results = [r for r in result.results if r.kind == "initial"]
        assert len(initial_results) == 0

    def test_backward_compatible(self):
        result = verify_spec(NoInitialSpec)
        assert result.passed


class TestMultipleInitials:
    def test_all_pass(self):
        result = verify_spec(MultipleInitialsSpec)
        initial_results = [r for r in result.results if r.kind == "initial"]
        assert len(initial_results) == 2
        assert all(r.status == "pass" for r in initial_results)

    def test_one_fails(self):
        result = verify_spec(MultipleInitialsOneFailsSpec)
        initial_results = [r for r in result.results if r.kind == "initial"]
        assert len(initial_results) == 2
        statuses = {r.property_name: r.status for r in initial_results}
        assert statuses["start_zeros"] == "pass"
        assert statuses["start_too_big"] == "fail"
