"""Broken ML pipeline spec — submit_job doesn't check VRAM capacity.

Bug: submit_job allows allocating VRAM without checking
vram_allocated + vram_req <= vram_capacity. This violates
the vram_bounded invariant.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, BoundedFloat, Nat
from praxis.decorators import require


class BrokenTrainingSpec(Spec):
    vram_capacity: BoundedInt[1, 640]
    vram_allocated: BoundedInt[0, 640]
    active_jobs: Nat

    @invariant
    def vram_bounded(self):
        return self.vram_allocated <= self.vram_capacity

    @invariant
    def resources_non_negative(self):
        return And(self.vram_allocated >= 0, self.active_jobs >= 0)

    @transition
    def submit_job(self, vram_req: BoundedInt[1, 80]):
        """BUG: Missing VRAM capacity check."""
        # Missing: require(self.vram_allocated + vram_req <= self.vram_capacity)
        self.vram_allocated += vram_req
        self.active_jobs += 1

    @transition
    def preempt_job(self, vram_req: BoundedInt[1, 80]):
        require(self.active_jobs > 0)
        require(self.vram_allocated >= vram_req)
        self.vram_allocated -= vram_req
        self.active_jobs -= 1
