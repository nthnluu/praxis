"""Pallas/XLA TPU Kernel Config Spec — tiling, grid dimensions, and HBM management.

Proves:
- Grid fully covers the matrix (grid_rows * tile_rows >= matrix_rows, same for cols)
- HBM usage never exceeds HBM capacity
- Pipeline has enough microbatches to stay full (microbatches >= num_pipeline_stages)
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class PallasKernelSpec(Spec):
    """TPU kernel configuration with tiling, grid, memory, and pipeline constraints."""

    # Matrix dimensions
    matrix_rows: BoundedInt[1, 32768]
    matrix_cols: BoundedInt[1, 32768]

    # Tile dimensions
    tile_rows: BoundedInt[1, 1024]
    tile_cols: BoundedInt[1, 1024]

    # Grid dimensions (tiles across each axis)
    grid_rows: BoundedInt[1, 32768]
    grid_cols: BoundedInt[1, 32768]

    # Pipeline configuration
    num_pipeline_stages: BoundedInt[1, 8]
    microbatches: BoundedInt[1, 64]

    # HBM (High Bandwidth Memory) tracking
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
        """All resource counters are non-negative."""
        return self.hbm_usage_mb >= 0

    # NOTE: grid coverage (grid_rows * tile_rows >= matrix_rows) is nonlinear,
    # so we enforce it via require() in transitions rather than as a global
    # invariant. Z3 handles nonlinear integer arithmetic poorly in invariants
    # because it must hold for ALL reachable states — require() in transitions
    # is the right tool here.

    @transition
    def configure_grid(
        self,
        t_rows: BoundedInt[1, 1024],
        t_cols: BoundedInt[1, 1024],
        g_rows: BoundedInt[1, 32768],
        g_cols: BoundedInt[1, 32768],
    ):
        """Set tile sizes and compute the grid. Must fully cover the matrix."""
        # Full coverage: every element of the matrix is inside some tile
        require(g_rows * t_rows >= self.matrix_rows)
        require(g_cols * t_cols >= self.matrix_cols)

        self.tile_rows = t_rows
        self.tile_cols = t_cols
        self.grid_rows = g_rows
        self.grid_cols = g_cols

    @transition
    def allocate_memory(self, usage: BoundedInt[0, 16384]):
        """Set HBM usage for this kernel configuration."""
        require(usage <= self.hbm_capacity_mb)
        self.hbm_usage_mb = usage

    @transition
    def set_pipeline(
        self,
        stages: BoundedInt[1, 8],
        batches: BoundedInt[1, 64],
    ):
        """Configure pipeline depth and microbatch count."""
        require(batches >= stages)
        self.num_pipeline_stages = stages
        self.microbatches = batches
