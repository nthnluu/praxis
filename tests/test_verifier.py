"""Tests for praxis.engine.verifier."""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, BoundedFloat
from praxis.decorators import require
from praxis.engine.verifier import verify_spec


class CorrectSpec(Spec):
    """A correct spec — all invariants provable from bounds, transitions guarded."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def non_negative(self):
        return And(self.x >= 0, self.y >= 0)

    @invariant
    def bounded_sum(self):
        return self.x + self.y <= 200

    @transition
    def increase_x(self, delta: BoundedInt[1, 10]):
        require(self.x + delta <= 100)
        self.x += delta

    @transition
    def decrease_x(self, delta: BoundedInt[1, 10]):
        require(self.x >= delta)
        self.x -= delta


class BrokenGPUSpec(Spec):
    """Missing the capacity check — should fail."""
    vram_total: BoundedInt[1, 640]
    vram_used: BoundedInt[0, 640]

    @invariant
    def no_overcommit(self):
        return self.vram_used <= self.vram_total

    @transition
    def schedule_job(self, job_vram: BoundedInt[1, 80]):
        # Missing: require(self.vram_used + job_vram <= self.vram_total)
        self.vram_used += job_vram


class ImpossibleInvariantSpec(Spec):
    """Invariant x > 100 with BoundedInt[0, 100] — always fails."""
    x: BoundedInt[0, 100]

    @invariant
    def impossible(self):
        return self.x > 100


class TestVerifyCorrectSpec:
    def test_all_pass(self):
        result = verify_spec(CorrectSpec)
        assert result.passed, [
            f"{r.property_name}: {r.status} - {r.error_message or ''}"
            for r in result.results if r.status != "pass"
        ]

    def test_result_counts(self):
        result = verify_spec(CorrectSpec)
        # 2 invariants + 2 transitions = 4 checks
        assert len(result.results) == 4
        assert result.pass_count == 4
        assert result.fail_count == 0


class TestVerifyBrokenSpec:
    def test_finds_counterexample(self):
        result = verify_spec(BrokenGPUSpec)
        assert not result.passed
        assert result.fail_count >= 1

    def test_counterexample_round_trip(self):
        """The counterexample should actually violate the invariant."""
        result = verify_spec(BrokenGPUSpec)
        fails = [r for r in result.results if r.status == "fail"]
        assert len(fails) >= 1
        for fail in fails:
            ce = fail.counterexample
            assert ce is not None
            if ce.after and ce.before:
                after_used = ce.after.get("vram_used", 0)
                before_total = ce.before.get("vram_total", 0)
                assert after_used > before_total, (
                    f"Counterexample doesn't demonstrate violation: "
                    f"vram_used'={after_used}, vram_total={before_total}"
                )


class TestVerifyImpossibleInvariant:
    def test_reports_failure(self):
        result = verify_spec(ImpossibleInvariantSpec)
        assert not result.passed
        inv_result = result.results[0]
        assert inv_result.status == "fail"
        assert inv_result.counterexample is not None


class TestTimeout:
    def test_timeout_handled(self):
        result = verify_spec(CorrectSpec, timeout_ms=1)
        for r in result.results:
            assert r.status in ("pass", "fail", "timeout", "error")
