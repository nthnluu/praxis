"""Broken Pallas kernel spec — allocate_memory doesn't check HBM capacity.

Bug: allocate_memory sets hbm_usage_mb without requiring usage <= hbm_capacity_mb.
This violates the hbm_bounded invariant.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenPallasKernelSpec(Spec):
    """TPU kernel config spec with a missing HBM guard."""

    matrix_rows: BoundedInt[1, 32768]
    matrix_cols: BoundedInt[1, 32768]

    tile_rows: BoundedInt[1, 1024]
    tile_cols: BoundedInt[1, 1024]

    grid_rows: BoundedInt[1, 32768]
    grid_cols: BoundedInt[1, 32768]

    num_pipeline_stages: BoundedInt[1, 8]
    microbatches: BoundedInt[1, 64]

    hbm_usage_mb: BoundedInt[0, 16384]
    hbm_capacity_mb: BoundedInt[1, 16384]

    @invariant
    def hbm_bounded(self):
        """HBM usage never exceeds physical capacity."""
        return self.hbm_usage_mb <= self.hbm_capacity_mb

    @invariant
    def pipeline_filled(self):
        """Enough microbatches to keep the pipeline busy."""
        return self.microbatches >= self.num_pipeline_stages

    @invariant
    def resources_non_negative(self):
        return self.hbm_usage_mb >= 0

    @transition
    def configure_grid(
        self,
        t_rows: BoundedInt[1, 1024],
        t_cols: BoundedInt[1, 1024],
        g_rows: BoundedInt[1, 32768],
        g_cols: BoundedInt[1, 32768],
    ):
        require(g_rows * t_rows >= self.matrix_rows)
        require(g_cols * t_cols >= self.matrix_cols)
        self.tile_rows = t_rows
        self.tile_cols = t_cols
        self.grid_rows = g_rows
        self.grid_cols = g_cols

    @transition
    def allocate_memory(self, usage: BoundedInt[0, 16384]):
        """BUG: Missing require(usage <= self.hbm_capacity_mb)."""
        # Missing: require(usage <= self.hbm_capacity_mb)
        self.hbm_usage_mb = usage

    @transition
    def set_pipeline(
        self,
        stages: BoundedInt[1, 8],
        batches: BoundedInt[1, 64],
    ):
        require(batches >= stages)
        self.num_pipeline_stages = stages
        self.microbatches = batches
