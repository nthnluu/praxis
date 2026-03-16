"""GPU Scheduler specification — the canonical Praxis example."""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, BoundedFloat
from praxis.decorators import require


class GPUSchedulerSpec(Spec):
    """Proves that no scheduling decision ever overcommits VRAM."""

    vram_total: BoundedInt[1, 640]
    vram_used: BoundedInt[0, 640]
    job_count: BoundedInt[0, 100]
    budget_per_hour: BoundedFloat[0.0, 10000.0]
    cost_per_hour: BoundedFloat[0.0, 10000.0]

    @invariant
    def no_overcommit(self):
        """VRAM usage never exceeds capacity."""
        return self.vram_used <= self.vram_total

    @invariant
    def non_negative_resources(self):
        """Resources are never negative."""
        return And(self.vram_used >= 0, self.job_count >= 0)

    @invariant
    def budget_respected(self):
        """Hourly spend never exceeds budget."""
        return self.cost_per_hour <= self.budget_per_hour

    @transition
    def schedule_job(self, job_vram: BoundedInt[1, 80], job_cost: BoundedFloat[0.0, 100.0]):
        """Assign a job to the cluster."""
        require(self.vram_used + job_vram <= self.vram_total)
        require(self.cost_per_hour + job_cost <= self.budget_per_hour)
        self.vram_used += job_vram
        self.cost_per_hour += job_cost
        self.job_count += 1

    @transition
    def release_job(self, job_vram: BoundedInt[1, 80], job_cost: BoundedFloat[0.0, 100.0]):
        """Release a job from the cluster."""
        require(self.job_count > 0)
        require(self.vram_used >= job_vram)
        require(self.cost_per_hour >= job_cost)
        self.vram_used -= job_vram
        self.cost_per_hour -= job_cost
        self.job_count -= 1
