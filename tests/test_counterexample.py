"""Tests for praxis.engine.counterexample."""

import z3
from praxis.engine.counterexample import (
    Counterexample,
    extract_counterexample_from_model,
)


class TestCounterexample:
    def test_human_format_invariant(self):
        ce = Counterexample(
            spec_name="TestSpec",
            property_name="no_overcommit",
            kind="invariant_violation",
            transition="schedule_job",
            before={"vram_total": 80, "vram_used": 48},
            inputs={"job_vram": 40},
            after={"vram_used": 88},
            explanation="vram_used' (88) exceeds vram_total (80)",
        )
        text = ce.to_human()
        assert "no_overcommit" in text
        assert "vram_total = 80" in text
        assert "job_vram = 40" in text
        assert "vram_used' = 88" in text

    def test_json_format(self):
        ce = Counterexample(
            spec_name="TestSpec",
            property_name="no_overcommit",
            kind="invariant_violation",
            transition="schedule_job",
            before={"vram_total": 80, "vram_used": 48},
            inputs={"job_vram": 40},
            after={"vram_used": 88},
        )
        j = ce.to_json()
        assert j["status"] == "FAIL"
        assert j["spec"] == "TestSpec"
        assert j["property"] == "no_overcommit"
        assert j["transition"] == "schedule_job"
        assert j["counterexample"]["before"]["vram_total"] == 80
        assert j["counterexample"]["inputs"]["job_vram"] == 40

    def test_standalone_invariant(self):
        ce = Counterexample(
            spec_name="TestSpec",
            property_name="always_positive",
            kind="invariant_inconsistency",
            before={"x": -5},
        )
        text = ce.to_human()
        assert "UNSATISFIABLE" in text
        assert "x = -5" in text


class TestExtractFromModel:
    def test_extract_int_model(self):
        x = z3.Int("x")
        y = z3.Int("y")
        s = z3.Solver()
        s.add(x == 42, y == 7)
        assert s.check() == z3.sat
        ce = extract_counterexample_from_model(
            model=s.model(),
            spec_name="TestSpec",
            property_name="test_prop",
            state_vars={"x": x, "y": y},
        )
        assert ce.before["x"] == 42
        assert ce.before["y"] == 7

    def test_extract_with_params(self):
        x = z3.Int("x")
        delta = z3.Int("param_delta")
        x_prime = z3.Int("x'")
        s = z3.Solver()
        s.add(x == 10, delta == 5, x_prime == 15)
        assert s.check() == z3.sat
        ce = extract_counterexample_from_model(
            model=s.model(),
            spec_name="TestSpec",
            property_name="test_prop",
            state_vars={"x": x},
            param_vars={"delta": delta},
            primed_vars={"x": x_prime},
            transition_name="update",
        )
        assert ce.before["x"] == 10
        assert ce.inputs["delta"] == 5
        assert ce.after["x"] == 15
        assert ce.transition == "update"
