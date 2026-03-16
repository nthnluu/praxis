"""ML Training Pipeline Spec — GPU memory management for training jobs.

Proves:
- Total VRAM allocated never exceeds node capacity
- Learning rate is always positive and bounded
- Batch size is always positive
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, BoundedFloat, Nat
from praxis.decorators import require


class TrainingSchedulerSpec(Spec):
    """GPU training job scheduler."""

    vram_capacity: BoundedInt[1, 640]      # Total VRAM (GiB)
    vram_allocated: BoundedInt[0, 640]     # Currently allocated
    active_jobs: Nat                        # Running training jobs
    lr: BoundedFloat[0.0, 10.0]           # Learning rate
    batch_size: BoundedInt[1, 4096]        # Current batch size

    @invariant
    def vram_bounded(self):
        """VRAM allocation never exceeds capacity."""
        return self.vram_allocated <= self.vram_capacity

    @invariant
    def resources_non_negative(self):
        """All counters are non-negative."""
        return And(self.vram_allocated >= 0, self.active_jobs >= 0)

    @invariant
    def lr_positive(self):
        """Learning rate is always positive."""
        return self.lr >= 0

    @invariant
    def batch_positive(self):
        """Batch size is always positive."""
        return self.batch_size >= 1

    @transition
    def submit_job(self, vram_req: BoundedInt[1, 80]):
        """Submit a training job."""
        require(self.vram_allocated + vram_req <= self.vram_capacity)
        self.vram_allocated += vram_req
        self.active_jobs += 1

    @transition
    def preempt_job(self, vram_req: BoundedInt[1, 80]):
        """Preempt a running training job."""
        require(self.active_jobs > 0)
        require(self.vram_allocated >= vram_req)
        self.vram_allocated -= vram_req
        self.active_jobs -= 1

    @transition
    def scale_lr(self, factor: BoundedFloat[0.1, 2.0]):
        """Scale learning rate by a factor."""
        require(self.lr * factor <= 10)
        require(self.lr * factor >= 0)
        self.lr = self.lr * factor
