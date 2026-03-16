"""Pallas/XLA TPU kernel configuration — tiling, grid computation, and HBM tracking.

Models the config layer between a high-level matmul and TPU execution:
tile sizing, grid layout, HBM budget, and pipeline scheduling.
Does not import JAX — this is pure config logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class KernelError(Exception):
    """Base error for kernel configuration problems."""


class GridCoverageError(KernelError):
    """Grid does not fully cover the matrix."""


class HBMOverflowError(KernelError):
    """HBM usage would exceed physical capacity."""


class PipelineError(KernelError):
    """Pipeline configuration is invalid."""


class TileAlignment(Enum):
    EXACT = auto()      # matrix_dim % tile_dim == 0
    PADDED = auto()     # last tile has padding


@dataclass(frozen=True)
class TileSpec:
    """A tile shape for one axis."""
    tile_size: int
    grid_size: int
    matrix_size: int
    alignment: TileAlignment

    @property
    def coverage(self) -> int:
        return self.tile_size * self.grid_size

    @property
    def waste_elements(self) -> int:
        return max(0, self.coverage - self.matrix_size)

    @property
    def utilization(self) -> float:
        """Fraction of tile space holding real data. 1.0 = no waste."""
        return self.matrix_size / self.coverage if self.coverage else 0.0


@dataclass
class HBMBudget:
    """Tracks high-bandwidth memory allocation for a kernel."""
    capacity_mb: int
    _allocations: dict[str, int] = field(default_factory=dict)

    @property
    def used_mb(self) -> int:
        return sum(self._allocations.values())

    @property
    def free_mb(self) -> int:
        return self.capacity_mb - self.used_mb

    def allocate(self, label: str, size_mb: int) -> None:
        """Reserve HBM for a buffer."""
        if size_mb < 0:
            raise ValueError(f"Allocation size must be non-negative, got {size_mb}")
        if self.used_mb + size_mb > self.capacity_mb:
            raise HBMOverflowError(
                f"'{label}' ({size_mb} MB) would exceed capacity "
                f"({self.used_mb + size_mb} > {self.capacity_mb})"
            )
        self._allocations[label] = size_mb

    def free(self, label: str) -> int:
        """Release an allocation. Returns freed MB."""
        return self._allocations.pop(label, 0)


@dataclass
class PipelineSchedule:
    """Pipeline schedule for overlapping compute and memory transfers."""
    num_stages: int
    microbatches: int

    def __post_init__(self):
        if self.num_stages < 1:
            raise PipelineError("Need at least 1 pipeline stage")
        if self.microbatches < 1:
            raise PipelineError("Need at least 1 microbatch")
        if self.microbatches < self.num_stages:
            raise PipelineError(
                f"Need at least {self.num_stages} microbatches to fill "
                f"{self.num_stages} pipeline stages, got {self.microbatches}"
            )

    @property
    def bubble_fraction(self) -> float:
        """Fraction of slots wasted in pipeline bubbles: (k-1)/(m+k-1)."""
        return (self.num_stages - 1) / (self.microbatches + self.num_stages - 1)

    @property
    def steady_state_steps(self) -> int:
        """Steps where all stages are active."""
        return self.microbatches - self.num_stages + 1


class GridComputation:
    """Computes and validates grid layout for a Pallas kernel."""

    @staticmethod
    def compute_grid_dim(matrix_dim: int, tile_dim: int) -> int:
        """ceil(matrix_dim / tile_dim)."""
        if tile_dim <= 0:
            raise ValueError(f"Tile dimension must be positive, got {tile_dim}")
        if matrix_dim <= 0:
            raise ValueError(f"Matrix dimension must be positive, got {matrix_dim}")
        return (matrix_dim + tile_dim - 1) // tile_dim

    @staticmethod
    def compute_tile_spec(matrix_dim: int, tile_dim: int) -> TileSpec:
        grid_dim = GridComputation.compute_grid_dim(matrix_dim, tile_dim)
        alignment = TileAlignment.EXACT if grid_dim * tile_dim == matrix_dim else TileAlignment.PADDED
        return TileSpec(tile_size=tile_dim, grid_size=grid_dim,
                        matrix_size=matrix_dim, alignment=alignment)

    @staticmethod
    def validate_coverage(matrix_rows: int, matrix_cols: int,
                          tile_rows: int, tile_cols: int,
                          grid_rows: int, grid_cols: int) -> None:
        """Raise GridCoverageError if tiles don't fully cover the matrix."""
        errors = []
        if grid_rows * tile_rows < matrix_rows:
            errors.append(f"rows: {grid_rows}*{tile_rows} < {matrix_rows}")
        if grid_cols * tile_cols < matrix_cols:
            errors.append(f"cols: {grid_cols}*{tile_cols} < {matrix_cols}")
        if errors:
            raise GridCoverageError("Incomplete coverage: " + "; ".join(errors))


@dataclass
class PallasKernelConfig:
    """Full configuration for a Pallas TPU kernel."""

    matrix_rows: int
    matrix_cols: int
    tile_rows: int
    tile_cols: int
    hbm_capacity_mb: int
    pipeline_stages: int = 1
    pipeline_microbatches: int = 1

    def __post_init__(self):
        for name in ("matrix_rows", "matrix_cols", "tile_rows", "tile_cols", "hbm_capacity_mb"):
            if getattr(self, name) < 1:
                raise ValueError(f"{name} must be >= 1, got {getattr(self, name)}")

    @property
    def row_spec(self) -> TileSpec:
        return GridComputation.compute_tile_spec(self.matrix_rows, self.tile_rows)

    @property
    def col_spec(self) -> TileSpec:
        return GridComputation.compute_tile_spec(self.matrix_cols, self.tile_cols)

    @property
    def grid_shape(self) -> tuple[int, int]:
        return (self.row_spec.grid_size, self.col_spec.grid_size)

    @property
    def total_tiles(self) -> int:
        r, c = self.grid_shape
        return r * c

    @property
    def utilization(self) -> float:
        """Overall tile utilization (product of row and col utilization)."""
        return self.row_spec.utilization * self.col_spec.utilization

    def make_hbm_budget(self) -> HBMBudget:
        return HBMBudget(capacity_mb=self.hbm_capacity_mb)

    def make_pipeline(self) -> PipelineSchedule:
        return PipelineSchedule(num_stages=self.pipeline_stages,
                                microbatches=self.pipeline_microbatches)

    def validate(self) -> None:
        """Run all validation checks. Raises on first failure."""
        r, c = self.grid_shape
        GridComputation.validate_coverage(
            self.matrix_rows, self.matrix_cols,
            self.tile_rows, self.tile_cols, r, c)
        self.make_pipeline()  # validates pipeline constraints
