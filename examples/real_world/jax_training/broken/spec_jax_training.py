"""Broken JAX training spec — submit_job doesn't check VRAM capacity.

Bug: submit_job allocates VRAM without verifying the total stays within
cluster limits. Praxis finds a counterexample: submit enough jobs to
exceed 5120 GiB and the vram_not_overcommitted invariant breaks.

This is the exact bug that causes GPU OOM kills in shared clusters.
The scheduler says "yes" to every job, VRAM fills up, and the next
CUDA malloc takes down every running job on the node.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, BoundedFloat
from praxis.decorators import require


class BrokenJaxTrainingSpec(Spec):
    """JAX training spec with missing VRAM guard."""

    num_devices: BoundedInt[1, 64]
    per_device_vram: BoundedInt[16, 80]
    total_vram_allocated: BoundedInt[0, 5120]

    micro_batch_size: BoundedInt[1, 512]
    accumulation_steps: BoundedInt[1, 64]
    effective_batch_size: BoundedInt[1, 32768]

    learning_rate: BoundedFloat[0.0, 10.0]
    num_shards: BoundedInt[1, 64]

    @invariant
    def vram_not_overcommitted(self):
        return self.total_vram_allocated <= 5120

    @invariant
    def vram_non_negative(self):
        return self.total_vram_allocated >= 0

    @invariant
    def lr_positive(self):
        return self.learning_rate > 0

    @invariant
    def shards_fit_devices(self):
        return self.num_shards <= self.num_devices

    @invariant
    def batch_sizes_positive(self):
        return And(
            self.micro_batch_size >= 1,
            self.accumulation_steps >= 1,
            self.effective_batch_size >= 1,
        )

    @transition
    def submit_job(self, vram_req: BoundedInt[1, 80]):
        """BUG: No capacity check. Allocates VRAM unconditionally.

        Missing: require(self.total_vram_allocated + vram_req <= 5120)
        """
        # Missing the critical guard:
        # require(self.total_vram_allocated + vram_req <= 5120)
        self.total_vram_allocated += vram_req

    @transition
    def release_job(self, vram_req: BoundedInt[1, 80]):
        require(self.total_vram_allocated >= vram_req)
        self.total_vram_allocated -= vram_req

    @transition
    def scale_batch(self, new_micro: BoundedInt[1, 512], new_accum: BoundedInt[1, 64],
                    new_effective: BoundedInt[1, 32768]):
        require(new_effective >= new_micro)
        require(new_effective >= new_accum)
        self.micro_batch_size = new_micro
        self.accumulation_steps = new_accum
        self.effective_batch_size = new_effective

    @transition
    def update_lr(self, factor: BoundedFloat[0.01, 10.0]):
        require(self.learning_rate * factor > 0)
        require(self.learning_rate * factor <= 10)
        self.learning_rate = self.learning_rate * factor

    @transition
    def reshard(self, new_shards: BoundedInt[1, 64]):
        require(new_shards <= self.num_devices)
        self.num_shards = new_shards
