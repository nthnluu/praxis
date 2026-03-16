"""Adversarial tests designed to expose bugs, crashes, or incorrect behavior in Praxis."""

import pytest
import time

from praxis import Spec, invariant, transition, require, runtime_guard, And, Or, Not, implies
from praxis.types import BoundedInt, Bool
from praxis.engine.verifier import verify_spec


# ============================================================
# 1. Contradictory invariants
# ============================================================

class Contradictory(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def high(self):
        return self.x > 50

    @invariant
    def low(self):
        return self.x < 50


def test_contradictory_invariants():
    """Praxis should detect that x > 50 and x < 50 are mutually unsatisfiable."""
    result = verify_spec(Contradictory)
    assert not result.passed, "Should have detected contradiction"
    # Both invariants should be marked as failing
    assert result.fail_count >= 1
    for r in result.results:
        if r.status == "fail":
            assert r.counterexample is not None
            assert "contradictory" in r.counterexample.explanation.lower() or \
                   "inconsisten" in r.counterexample.explanation.lower()


# ============================================================
# 2. Very large bounds (2**63 - 1)
# ============================================================

class BigBounds(Spec):
    x: BoundedInt[0, 2**63 - 1]

    @invariant
    def pos(self):
        return self.x >= 0


def test_big_bounds_no_crash():
    """Z3 should handle 64-bit bounds without crashing."""
    result = verify_spec(BigBounds, timeout_ms=10000)
    # This invariant is trivially true given bounds [0, 2^63-1]
    assert result.passed or any(r.status == "timeout" for r in result.results), \
        f"Expected pass or timeout, got: {[(r.property_name, r.status) for r in result.results]}"


# ============================================================
# 3. Nonlinear arithmetic (multiplication of two bounded vars)
# ============================================================

class Nonlinear(Spec):
    x: BoundedInt[0, 1000000]
    y: BoundedInt[0, 1000000]

    @invariant
    def bounded_product(self):
        return self.x * self.y <= 1000000000000


def test_nonlinear_no_crash():
    """Z3 may timeout on nonlinear arithmetic but should not crash."""
    result = verify_spec(Nonlinear, timeout_ms=5000, fuzz_count=100)
    # Should either pass, fail, or timeout -- never crash
    assert result is not None
    for r in result.results:
        assert r.status in ("pass", "fail", "timeout", "error"), \
            f"Unexpected status: {r.status}"


# ============================================================
# 4. Spec with 50 fields -- performance test
# ============================================================

# Dynamically create a spec with 50 fields
_fifty_fields_ns = {"__annotations__": {}}
for _i in range(50):
    _fifty_fields_ns["__annotations__"][f"f{_i}"] = BoundedInt[0, 100]


def _sum_invariant(self):
    total = 0
    for i in range(50):
        total += getattr(self, f"f{i}")
    return total >= 0


_sum_invariant._praxis_invariant = True
_fifty_fields_ns["sum_positive"] = _sum_invariant

FiftyFields = type("FiftyFields", (Spec,), _fifty_fields_ns)


def test_fifty_fields_performance():
    """50 fields should verify within a reasonable time."""
    start = time.time()
    result = verify_spec(FiftyFields, timeout_ms=10000)
    elapsed = time.time() - start
    # Should complete within 30 seconds (generous budget)
    assert elapsed < 30, f"Took {elapsed:.1f}s -- too slow"
    assert result is not None


# ============================================================
# 5. Deeply nested boolean expressions
# ============================================================

class DeeplyNested(Spec):
    a: BoundedInt[0, 100]
    b: BoundedInt[0, 100]
    c: BoundedInt[0, 100]

    @invariant
    def nested(self):
        return And(
            Or(self.a > 0, self.b > 0),
            Or(
                And(self.a <= 100, self.b <= 100),
                And(self.c > 0, self.c <= 100)
            ),
            implies(self.a > 50, self.b < 50),
            Or(self.c >= 0, Not(self.a > 0)),
        )


def test_deeply_nested_booleans():
    """Deeply nested boolean expressions should verify without issues."""
    result = verify_spec(DeeplyNested)
    assert result is not None
    for r in result.results:
        assert r.status in ("pass", "fail", "timeout"), f"Unexpected: {r.status}"


# ============================================================
# 6. Invariant referencing a field that doesn't exist
# ============================================================

class NonexistentField(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def bad_ref(self):
        return self.y > 0  # 'y' is not a declared field


def test_nonexistent_field():
    """Referencing a non-existent field should produce an error, not crash."""
    result = verify_spec(NonexistentField)
    # Should get an error status, not a Python crash
    assert not result.passed
    has_error = any(r.status == "error" for r in result.results)
    has_fail = any(r.status == "fail" for r in result.results)
    assert has_error or has_fail, \
        f"Expected error or fail for nonexistent field, got: {[(r.property_name, r.status, r.error_message) for r in result.results]}"


# ============================================================
# 7. Transition modifying a field not in the spec
# ============================================================

class GhostFieldTransition(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def positive(self):
        return self.x >= 0

    @transition
    def bad_mutation(self, amount: BoundedInt[0, 50]):
        self.z = amount  # 'z' is not a declared field


def test_transition_modifies_ghost_field():
    """Transition modifying a non-existent field should produce an error with a clear message."""
    result = verify_spec(GhostFieldTransition)
    trans_results = [r for r in result.results if r.kind == "transition"]
    assert len(trans_results) == 1
    assert trans_results[0].status == "error"
    # Error message should mention the field name and that it's not declared
    assert "z" in trans_results[0].error_message
    assert "not a declared state field" in trans_results[0].error_message


# ============================================================
# 8. Empty spec (no fields, no invariants)
# ============================================================

class EmptySpec(Spec):
    pass


def test_empty_spec():
    """Empty spec should verify without crashing."""
    result = verify_spec(EmptySpec)
    assert result is not None
    assert result.passed  # vacuously true
    assert result.pass_count == 0
    assert result.fail_count == 0


# ============================================================
# 9. Transition with 20 require() clauses
# ============================================================

class ManyRequires(Spec):
    x: BoundedInt[0, 1000]

    @invariant
    def bounded(self):
        return self.x >= 0

    @transition
    def guarded(self, amount: BoundedInt[0, 100]):
        require(amount > 0)
        require(amount < 100)
        require(amount != 50)
        require(self.x >= 0)
        require(self.x < 900)
        require(amount >= 1)
        require(amount <= 99)
        require(self.x + amount <= 1000)
        require(amount != 25)
        require(amount != 75)
        require(self.x != 500)
        require(self.x != 501)
        require(self.x != 502)
        require(amount >= 2)
        require(amount <= 98)
        require(self.x < 800)
        require(self.x >= 1)
        require(amount != 10)
        require(amount != 90)
        require(self.x + amount >= 1)
        self.x = self.x + amount


def test_many_requires():
    """20 require() clauses should be handled correctly."""
    result = verify_spec(ManyRequires)
    assert result is not None
    trans_results = [r for r in result.results if r.kind == "transition"]
    assert len(trans_results) == 1
    # The transition preserves x >= 0 since all inputs are positive
    assert trans_results[0].status == "pass"


# ============================================================
# 10. runtime_guard with a state_extractor that throws
# ============================================================

class SimpleGuardSpec(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def positive(self):
        return self.x >= 0


def test_runtime_guard_extractor_throws():
    """runtime_guard with a broken state_extractor should propagate the exception clearly."""

    def bad_extractor(obj):
        raise RuntimeError("Extractor exploded!")

    @runtime_guard(SimpleGuardSpec, state_extractor=bad_extractor)
    def my_func(obj):
        obj.value = 42

    class FakeObj:
        value = 10

    # Should raise RuntimeError (from the extractor), not some internal Praxis error
    with pytest.raises(RuntimeError, match="Extractor exploded"):
        my_func(FakeObj())


# ============================================================
# 11. Spec with only invariants, no transitions
# ============================================================

class InvariantsOnly(Spec):
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def sum_bounded(self):
        return self.x + self.y <= 200

    @invariant
    def both_positive(self):
        return self.x >= 0


def test_invariants_only():
    """Spec with only invariants should verify they are satisfiable."""
    result = verify_spec(InvariantsOnly)
    assert result.passed


# ============================================================
# 12. Spec with only transitions, no invariants
# ============================================================

class TransitionsOnly(Spec):
    x: BoundedInt[0, 100]

    @transition
    def bump(self, amount: BoundedInt[1, 10]):
        self.x = self.x + amount


def test_transitions_only():
    """Spec with transitions but no invariants should not crash."""
    result = verify_spec(TransitionsOnly)
    assert result is not None
    # No invariants to verify, so should vacuously pass


# ============================================================
# 13. Invariant that always returns True
# ============================================================

class TrivialTrue(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def always_true(self):
        return True


def test_trivial_true():
    result = verify_spec(TrivialTrue)
    assert result.passed


# ============================================================
# 14. Invariant that always returns False
# ============================================================

class TrivialFalse(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def always_false(self):
        return False


def test_trivial_false():
    """An invariant returning False should always fail."""
    result = verify_spec(TrivialFalse)
    assert not result.passed
    assert result.fail_count >= 1


# ============================================================
# 15. Transition with zero-width type range
# ============================================================

class ZeroWidthParam(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def positive(self):
        return self.x >= 0

    @transition
    def set_exact(self, val: BoundedInt[42, 42]):
        self.x = val


def test_zero_width_param():
    """BoundedInt[42, 42] should work (val is always 42)."""
    result = verify_spec(ZeroWidthParam)
    assert result is not None
    for r in result.results:
        assert r.status in ("pass", "fail", "timeout")


# ============================================================
# 16. Transition that makes invariant fail (should detect violation)
# ============================================================

class OverflowTransition(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def bounded(self):
        return self.x <= 100

    @transition
    def double(self, amount: BoundedInt[1, 100]):
        self.x = self.x + amount  # can exceed 100


def test_overflow_detected():
    """Transition that can violate invariant should be caught."""
    result = verify_spec(OverflowTransition)
    trans_results = [r for r in result.results if r.kind == "transition"]
    assert len(trans_results) == 1
    assert trans_results[0].status == "fail"


# ============================================================
# 17. Spec with Bool fields
# ============================================================

class BoolSpec(Spec):
    active: Bool
    count: BoundedInt[0, 100]

    @invariant
    def active_means_positive(self):
        return implies(self.active, self.count > 0)


def test_bool_spec():
    """Spec with Bool fields should verify correctly."""
    result = verify_spec(BoolSpec)
    assert result.passed


# ============================================================
# 18. Transition with unannotated parameter
# ============================================================

class UnannotatedParam(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def positive(self):
        return self.x >= 0

    @transition
    def set_val(self, val):  # no annotation!
        self.x = val


def test_unannotated_param():
    """Transition parameter without annotation should produce clear error."""
    result = verify_spec(UnannotatedParam)
    trans_results = [r for r in result.results if r.kind == "transition"]
    assert len(trans_results) == 1
    assert trans_results[0].status == "error"
    assert "annotation" in trans_results[0].error_message.lower()


# ============================================================
# 19. Verify x == 50 exact: contradiction with x > 50 AND x < 50
#     but NOT with x >= 50 AND x <= 50
# ============================================================

class ExactBoundary(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def at_least_50(self):
        return self.x >= 50

    @invariant
    def at_most_50(self):
        return self.x <= 50


def test_exact_boundary_satisfiable():
    """x >= 50 and x <= 50 should be satisfiable (x == 50)."""
    result = verify_spec(ExactBoundary)
    assert result.passed, f"Should be satisfiable at x=50, got: {[(r.property_name, r.status) for r in result.results]}"


# ============================================================
# 20. runtime_guard with None state_extractor
# ============================================================

def test_runtime_guard_no_extractor():
    """runtime_guard with no state_extractor should still work (no checks)."""

    @runtime_guard(SimpleGuardSpec, state_extractor=None)
    def my_func(x):
        return x + 1

    # Should not crash, just pass through
    assert my_func(5) == 6


# ============================================================
# 21. Multiple transitions, one good one bad
# ============================================================

# ============================================================
# 22. Transition with pass body (no-op)
# ============================================================

class NoOpTransition(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def pos(self):
        return self.x >= 0

    @transition
    def noop(self, v: BoundedInt[0, 10]):
        pass  # empty body


def test_noop_transition():
    """A transition with just 'pass' should be a valid no-op."""
    result = verify_spec(NoOpTransition)
    trans_results = [r for r in result.results if r.kind == "transition"]
    assert len(trans_results) == 1
    assert trans_results[0].status == "pass", \
        f"No-op transition should pass, got: {trans_results[0].status} ({trans_results[0].error_message})"


# ============================================================
# 23. Transition with docstring only
# ============================================================

class DocstringTransition(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def pos(self):
        return self.x >= 0

    @transition
    def documented_noop(self, v: BoundedInt[0, 10]):
        """This transition does nothing."""
        pass


def test_docstring_transition():
    """A transition with a docstring and pass should work."""
    result = verify_spec(DocstringTransition)
    trans_results = [r for r in result.results if r.kind == "transition"]
    assert len(trans_results) == 1
    assert trans_results[0].status == "pass"


# ============================================================
# 24. Invariant with docstring
# ============================================================

class DocstringInvariant(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def bounded(self):
        """x must be at most 100."""
        return self.x <= 100


def test_docstring_invariant():
    """Invariants with docstrings should parse correctly."""
    result = verify_spec(DocstringInvariant)
    assert result.passed


class MixedTransitions(Spec):
    balance: BoundedInt[0, 1000]

    @invariant
    def non_negative(self):
        return self.balance >= 0

    @transition
    def deposit(self, amount: BoundedInt[1, 100]):
        self.balance = self.balance + amount

    @transition
    def withdraw_unsafe(self, amount: BoundedInt[1, 100]):
        self.balance = self.balance - amount  # can go negative!


def test_mixed_transitions():
    """One good transition and one bad -- bad should fail, good should pass."""
    result = verify_spec(MixedTransitions)
    trans_results = {r.transition_name: r for r in result.results if r.kind == "transition"}
    assert trans_results["deposit"].status == "pass"
    assert trans_results["withdraw_unsafe"].status == "fail"
