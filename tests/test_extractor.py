"""Tests for praxis.compiler.extractor."""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, BoundedFloat
from praxis.decorators import require
from praxis.compiler.extractor import extract_spec


class GPUSchedulerSpec(Spec):
    """Test spec for extraction."""
    vram_total: BoundedInt[1, 640]
    vram_used: BoundedInt[0, 640]
    job_count: BoundedInt[0, 100]

    @invariant
    def no_overcommit(self):
        return self.vram_used <= self.vram_total

    @invariant
    def non_negative(self):
        return And(self.vram_used >= 0, self.job_count >= 0)

    @transition
    def schedule_job(self, job_vram: BoundedInt[1, 80]):
        """Assign a job."""
        require(self.vram_used + job_vram <= self.vram_total)
        self.vram_used += job_vram
        self.job_count += 1

    @transition
    def release_job(self, job_vram: BoundedInt[1, 80]):
        """Release a job."""
        require(self.job_count > 0)
        require(self.vram_used >= job_vram)
        self.vram_used -= job_vram
        self.job_count -= 1


class TestExtractor:
    def test_state_fields(self):
        result = extract_spec(GPUSchedulerSpec)
        assert set(result.state_fields.keys()) == {"vram_total", "vram_used", "job_count"}

    def test_invariants(self):
        result = extract_spec(GPUSchedulerSpec)
        names = {inv.name for inv in result.invariants}
        assert names == {"no_overcommit", "non_negative"}
        for inv in result.invariants:
            assert inv.source
            assert inv.ast_node is not None

    def test_transitions(self):
        result = extract_spec(GPUSchedulerSpec)
        names = {t.name for t in result.transitions}
        assert names == {"schedule_job", "release_job"}

    def test_transition_params(self):
        result = extract_spec(GPUSchedulerSpec)
        schedule = [t for t in result.transitions if t.name == "schedule_job"][0]
        assert len(schedule.params) == 1
        assert schedule.params[0].name == "job_vram"
        assert schedule.params[0].annotation is not None

    def test_spec_name(self):
        result = extract_spec(GPUSchedulerSpec)
        assert result.name == "GPUSchedulerSpec"
