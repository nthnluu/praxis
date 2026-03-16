"""Tier 2: Verification correctness tests — hand-verified known answers.

Every spec here has a mathematically known correct answer.
If any of these flip, something is fundamentally broken.
"""

from praxis import Spec, invariant, transition, And, Or, Not, implies
from praxis.types import BoundedInt, BoundedFloat, Nat
from praxis.decorators import require
from praxis.engine.verifier import verify_spec


# ============================================================
# SPECS THAT MUST PASS (prover confirms all invariants hold)
# ============================================================

class TrivialTrueSpec(Spec):
    """a. Trivial: x >= 0 is guaranteed by BoundedInt[0, 100]."""
    x: BoundedInt[0, 100]

    @invariant
    def non_negative(self):
        return self.x >= 0


class TightArithmeticSpec(Spec):
    """b. x + y <= 200 when both in [0, 100]."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def bounded_sum(self):
        return self.x + self.y <= 200


class GuardedTransitionSpec(Spec):
    """c. Transition with correct guards preserves invariant.

    The invariant x + y <= 200 holds from bounds.
    The transition guards ensure x stays bounded.
    """
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def bounded(self):
        return self.x + self.y <= 200

    @transition
    def increase_x(self, amount: BoundedInt[1, 10]):
        require(self.x + amount <= 100)
        self.x += amount


class MultipleInvariantsSpec(Spec):
    """d. Multiple invariants, all valid."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]
    z: BoundedInt[0, 100]

    @invariant
    def x_non_negative(self):
        return self.x >= 0

    @invariant
    def y_non_negative(self):
        return self.y >= 0

    @invariant
    def z_non_negative(self):
        return self.z >= 0

    @invariant
    def sum_bounded(self):
        return self.x + self.y + self.z <= 300


class SubtractionGuardSpec(Spec):
    """e. release with require(x >= amount) preserves x >= 0."""
    x: BoundedInt[0, 100]

    @invariant
    def non_negative(self):
        return self.x >= 0

    @transition
    def release(self, amount: BoundedInt[1, 10]):
        require(self.x >= amount)
        self.x -= amount


class IdempotentTransitionSpec(Spec):
    """f. self.x = self.x preserves all invariants."""
    x: BoundedInt[0, 100]

    @invariant
    def bounded(self):
        return And(self.x >= 0, self.x <= 100)

    @transition
    def noop(self, dummy: BoundedInt[0, 1]):
        self.x = self.x


class GuardHeavyTransitionSpec(Spec):
    """g. Transition with 4+ require() clauses."""
    a: BoundedInt[0, 100]
    b: BoundedInt[0, 100]
    c: BoundedInt[0, 100]
    d: BoundedInt[0, 100]

    @invariant
    def all_bounded(self):
        return And(self.a <= 100, self.b <= 100, self.c <= 100, self.d <= 100)

    @transition
    def complex_update(self, v: BoundedInt[1, 10]):
        require(self.a + v <= 100)
        require(self.b + v <= 100)
        require(self.c + v <= 100)
        require(self.d + v <= 100)
        self.a += v
        self.b += v
        self.c += v
        self.d += v


# ============================================================
# SPECS THAT MUST FAIL (prover finds counterexamples)
# ============================================================

class MissingGuardSpec(Spec):
    """h. Missing guard — prover must find overcommit.

    Invariant x <= 100 is provable from bounds, but transition
    can push x beyond 100 since x + amount can exceed 100.
    """
    x: BoundedInt[0, 100]

    @invariant
    def bounded(self):
        return self.x <= 100

    @transition
    def increase(self, amount: BoundedInt[1, 50]):
        # Missing: require(self.x + amount <= 100)
        self.x += amount


class OffByOneSpec(Spec):
    """i. Guard uses < instead of <= — boundary case.

    require(x + delta < 100) allows x=98, delta=1 → x'=99 (ok),
    but also x=99, delta=1: 99+1=100 which is NOT < 100, so blocked.
    Actually x=98, delta=2: 98+2=100 NOT < 100 blocked.
    Guard properly blocks. We need a different off-by-one.

    Use: require(x + delta < 110) instead of require(x + delta <= 100).
    This allows x=90, delta=15 → x'=105, violating x <= 100.
    """
    x: BoundedInt[0, 100]

    @invariant
    def bounded(self):
        return self.x <= 100

    @transition
    def increment(self, delta: BoundedInt[1, 20]):
        require(self.x + delta < 110)  # Off-by-one: should be <= 100
        self.x += delta


class WrongVariableSpec(Spec):
    """j. Guard checks wrong variable (copy-paste bug).

    x: capacity, y: used. Guard checks x (capacity) instead of y (used).
    """
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def y_bounded(self):
        return self.y <= 100

    @transition
    def update(self, amount: BoundedInt[1, 50]):
        require(self.x + amount <= 100)  # Wrong! should check y
        self.y += amount


class InsufficientGuardSpec(Spec):
    """k. Two invariants, only one guarded."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def x_bounded(self):
        return self.x <= 100

    @invariant
    def y_bounded(self):
        return self.y <= 100

    @transition
    def update(self, v: BoundedInt[1, 50]):
        require(self.x + v <= 100)  # Guards x but not y
        self.x += v
        self.y += v


class IntegerOverflowSpec(Spec):
    """l. x += y without guard, x can exceed 100."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def x_bounded(self):
        return self.x <= 100

    @transition
    def add(self, dummy: BoundedInt[0, 0]):
        self.x += self.y


class ContradictoryInvariantsSpec(Spec):
    """m. x > 50 AND x < 50 — contradictory."""
    x: BoundedInt[0, 100]

    @invariant
    def too_high(self):
        return self.x > 50

    @invariant
    def too_low(self):
        return self.x < 50


# ============================================================
# TEST CLASSES
# ============================================================

class TestMustPass:
    def test_trivial_true(self):
        result = verify_spec(TrivialTrueSpec)
        assert result.passed, _failures(result)

    def test_tight_arithmetic(self):
        result = verify_spec(TightArithmeticSpec)
        assert result.passed, _failures(result)

    def test_guarded_transition(self):
        result = verify_spec(GuardedTransitionSpec)
        assert result.passed, _failures(result)

    def test_multiple_invariants(self):
        result = verify_spec(MultipleInvariantsSpec)
        assert result.passed, _failures(result)

    def test_subtraction_guard(self):
        result = verify_spec(SubtractionGuardSpec)
        assert result.passed, _failures(result)

    def test_idempotent_transition(self):
        result = verify_spec(IdempotentTransitionSpec)
        assert result.passed, _failures(result)

    def test_guard_heavy(self):
        result = verify_spec(GuardHeavyTransitionSpec)
        assert result.passed, _failures(result)


class TestMustFail:
    def test_missing_guard(self):
        result = verify_spec(MissingGuardSpec)
        _assert_fails_with_valid_counterexample(result, "increase")

    def test_off_by_one(self):
        result = verify_spec(OffByOneSpec)
        _assert_fails_with_valid_counterexample(result, "increment")

    def test_wrong_variable(self):
        result = verify_spec(WrongVariableSpec)
        _assert_fails_with_valid_counterexample(result, "update")

    def test_insufficient_guard(self):
        result = verify_spec(InsufficientGuardSpec)
        _assert_fails_with_valid_counterexample(result, "update")

    def test_integer_overflow(self):
        result = verify_spec(IntegerOverflowSpec)
        _assert_fails_with_valid_counterexample(result, "add")

    def test_contradictory_invariants(self):
        result = verify_spec(ContradictoryInvariantsSpec)
        assert not result.passed
        fails = [r for r in result.results if r.status == "fail"]
        assert len(fails) >= 1


class TestCounterexampleRoundTrip:
    """n. For every failing spec, verify the counterexample reproduces concretely."""

    def test_missing_guard_roundtrip(self):
        _roundtrip_check(MissingGuardSpec, "increase", "bounded")

    def test_off_by_one_roundtrip(self):
        _roundtrip_check(OffByOneSpec, "increment", "bounded")

    def test_integer_overflow_roundtrip(self):
        _roundtrip_check(IntegerOverflowSpec, "add", "x_bounded")

    def test_insufficient_guard_roundtrip(self):
        _roundtrip_check(InsufficientGuardSpec, "update", "y_bounded")


# ============================================================
# Helpers
# ============================================================

def _failures(result):
    return [
        f"{r.property_name}: {r.status} - {r.error_message or (r.counterexample.to_human() if r.counterexample else '')}"
        for r in result.results if r.status != "pass"
    ]


def _assert_fails_with_valid_counterexample(result, transition_name):
    """Assert the spec fails and has a counterexample for the given transition."""
    assert not result.passed, f"Expected spec to fail but it passed"
    fails = [r for r in result.results if r.status == "fail" and r.transition_name == transition_name]
    assert len(fails) >= 1, f"No failure for transition {transition_name}: {_failures(result)}"
    for fail in fails:
        assert fail.counterexample is not None, "Failure has no counterexample"


def _roundtrip_check(spec_cls, transition_name, invariant_name):
    """Verify a counterexample reproduces concretely.

    Extracts the counterexample after-state and checks that the invariant
    is violated on those concrete values.
    """
    result = verify_spec(spec_cls)
    fails = [r for r in result.results if r.status == "fail" and r.transition_name == transition_name]
    assert len(fails) >= 1, f"No failure for transition {transition_name}"

    for fail in fails:
        ce = fail.counterexample
        assert ce is not None

        # Find the invariant method
        inv_method = None
        for i in spec_cls.invariants():
            if i.__name__ == invariant_name:
                inv_method = i
                break
        assert inv_method is not None, f"Invariant {invariant_name} not found"

        # Create object with after-state values
        obj = type("State", (), {})()
        # Start with before state
        for name, val in ce.before.items():
            setattr(obj, name, val)
        # Apply after state (primed values)
        for name, val in ce.after.items():
            setattr(obj, name, val)

        # Check the invariant on after-state — it should be violated
        inv_result = inv_method(obj)
        assert not inv_result, (
            f"SOUNDNESS BUG: counterexample before={ce.before} after={ce.after} "
            f"does NOT violate invariant {invariant_name}. Got {inv_result}"
        )
