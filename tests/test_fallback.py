"""Tests for praxis.engine.fallback."""

from praxis import Spec, invariant
from praxis.types import BoundedInt, Bool
from praxis.engine.fallback import fuzz_invariant, generate_strategy


class GoodSpec(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def always_true(self):
        return self.x >= 0


class BadSpec(Spec):
    x: BoundedInt[0, 100]

    @invariant
    def too_tight(self):
        return self.x > 50


class TestGenerateStrategy:
    def test_bounded_int(self):
        st = generate_strategy(BoundedInt[0, 100])
        assert st is not None

    def test_bool(self):
        st = generate_strategy(Bool)
        assert st is not None


class TestFuzzInvariant:
    def test_good_spec(self):
        result = fuzz_invariant(GoodSpec, GoodSpec.always_true, iterations=1000)
        assert result.passed
        assert result.violations == 0
        assert result.iterations == 1000

    def test_bad_spec(self):
        result = fuzz_invariant(BadSpec, BadSpec.too_tight, iterations=1000)
        assert not result.passed
        assert result.violations > 0
        assert len(result.violation_examples) > 0

    def test_human_output(self):
        result = fuzz_invariant(BadSpec, BadSpec.too_tight, iterations=100)
        text = result.to_human()
        assert "timed out" in text
        assert "100 inputs" in text
