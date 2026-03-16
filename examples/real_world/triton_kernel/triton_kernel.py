"""Triton-style GPU kernel configuration and launch management.

Models the core concerns of GPU kernel programming without importing
Triton itself: tile sizing, grid computation, shared memory budgeting,
and the coverage invariant that every element gets processed.

In real Triton code, getting the tile size wrong doesn't crash — the kernel
runs fine, it just silently skips elements at the tail. That's worse than
a crash. This module makes those invariants explicit and checkable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ── Hardware constants ──────────────────────────────────────────────

MAX_THREADS_PER_BLOCK = 1024
MAX_SHARED_MEMORY_BYTES = 49152  # 48 KB, typical for consumer GPUs
MAX_GRID_DIM = 65536
VALID_BLOCK_SIZES = [2**i for i in range(5, 11)]  # 32, 64, ..., 1024


class KernelConfigError(Exception):
    """Raised when a kernel configuration violates hardware constraints."""
    pass


class CoverageError(KernelConfigError):
    """Grid does not cover the full tensor."""
    pass


class SharedMemoryError(KernelConfigError):
    """Shared memory request exceeds hardware budget."""
    pass


class ThreadLimitError(KernelConfigError):
    """Thread count exceeds per-block maximum."""
    pass


# ── Data structures ─────────────────────────────────────────────────

@dataclass
class TensorDescriptor:
    """Describes a tensor to be processed by a kernel."""
    name: str
    dim: int                    # Number of elements along the tiled axis
    dtype_bytes: int = 4        # Bytes per element (float32 default)
    ndim: int = 1               # Total dimensions

    def __post_init__(self):
        if self.dim < 1:
            raise ValueError(f"Tensor dim must be >= 1, got {self.dim}")
        if self.dim > MAX_GRID_DIM * MAX_THREADS_PER_BLOCK:
            raise ValueError(f"Tensor dim {self.dim} exceeds maximum addressable elements")


@dataclass
class SharedMemoryAllocation:
    """A named shared memory region within a block."""
    name: str
    size_bytes: int
    purpose: str = ""

    def __post_init__(self):
        if self.size_bytes < 0:
            raise ValueError(f"Shared memory size must be >= 0, got {self.size_bytes}")


@dataclass(frozen=True)
class GridConfig:
    """Immutable snapshot of a kernel launch configuration."""
    block_size: int
    num_blocks: int
    threads_per_block: int
    elements_per_thread: int
    shared_memory_bytes: int
    tensor_dim: int

    @property
    def coverage(self) -> int:
        """Total elements the grid can process."""
        return self.num_blocks * self.block_size

    @property
    def utilization(self) -> float:
        """Fraction of grid slots that map to real tensor elements."""
        return self.tensor_dim / self.coverage if self.coverage > 0 else 0.0

    @property
    def waste(self) -> int:
        """Number of grid slots beyond what the tensor needs."""
        return self.coverage - self.tensor_dim


# ── Kernel launcher ────────────────────────────────────────────────

class KernelLauncher:
    """Manages GPU kernel configuration with safety checks.

    Enforces three properties at every configuration change:
    1. Full coverage: num_blocks * block_size >= tensor_dim
    2. Shared memory within budget
    3. Threads per block within hardware maximum

    These correspond to the invariants in the Praxis spec. If any
    check fails, the configuration is rejected — no partial updates.
    """

    def __init__(
        self,
        max_shared_memory: int = MAX_SHARED_MEMORY_BYTES,
        max_threads: int = MAX_THREADS_PER_BLOCK,
    ):
        self._max_shared_memory = max_shared_memory
        self._max_threads = max_threads
        self._tensor: TensorDescriptor | None = None
        self._block_size: int = 0
        self._num_blocks: int = 0
        self._threads_per_block: int = 0
        self._elements_per_thread: int = 1
        self._shared_mem_allocations: list[SharedMemoryAllocation] = []
        self._launch_count: int = 0

    # ── Configuration ───────────────────────────────────────────

    def set_tensor(self, tensor: TensorDescriptor) -> None:
        """Register the tensor this kernel will process."""
        self._tensor = tensor
        # If we already have a block size, recompute grid
        if self._block_size > 0:
            self._recompute_grid()

    def configure_kernel(
        self,
        block_size: int,
        threads_per_block: int | None = None,
        elements_per_thread: int = 1,
    ) -> GridConfig:
        """Set tile size and compute grid dimensions.

        This is where the coverage invariant is enforced. The block_size
        determines how many elements each block processes. We compute
        num_blocks = ceil(tensor_dim / block_size) to guarantee every
        element is covered.
        """
        if self._tensor is None:
            raise KernelConfigError("Must set tensor before configuring kernel")

        if block_size < 1 or block_size > 1024:
            raise KernelConfigError(f"block_size must be in [1, 1024], got {block_size}")

        if elements_per_thread < 1 or elements_per_thread > 64:
            raise KernelConfigError(
                f"elements_per_thread must be in [1, 64], got {elements_per_thread}"
            )

        tpb = threads_per_block if threads_per_block is not None else block_size
        if tpb < 1 or tpb > self._max_threads:
            raise ThreadLimitError(
                f"threads_per_block={tpb} exceeds limit of {self._max_threads}"
            )

        self._block_size = block_size
        self._threads_per_block = tpb
        self._elements_per_thread = elements_per_thread
        self._recompute_grid()

        return self.get_config()

    def allocate_shared_memory(
        self,
        name: str,
        size_bytes: int,
        purpose: str = "",
    ) -> int:
        """Reserve shared memory for a block-level buffer.

        Returns total shared memory after this allocation.
        Raises SharedMemoryError if the budget would be exceeded.
        """
        alloc = SharedMemoryAllocation(name=name, size_bytes=size_bytes, purpose=purpose)
        total = self.total_shared_memory + size_bytes
        if total > self._max_shared_memory:
            raise SharedMemoryError(
                f"Allocation '{name}' ({size_bytes}B) would bring total to "
                f"{total}B, exceeding limit of {self._max_shared_memory}B"
            )
        self._shared_mem_allocations.append(alloc)
        return total

    def free_shared_memory(self, name: str) -> int:
        """Release a shared memory allocation by name."""
        before = len(self._shared_mem_allocations)
        self._shared_mem_allocations = [
            a for a in self._shared_mem_allocations if a.name != name
        ]
        if len(self._shared_mem_allocations) == before:
            raise KernelConfigError(f"No shared memory allocation named '{name}'")
        return self.total_shared_memory

    def resize_tensor(self, new_dim: int) -> GridConfig:
        """Change the tensor size and recompute the grid.

        This is the operation most likely to introduce bugs: the tensor
        changes shape (e.g., variable-length sequence in a transformer),
        but the grid stays the same. Elements beyond the old grid are
        never touched.
        """
        if self._tensor is None:
            raise KernelConfigError("No tensor registered")
        if new_dim < 1 or new_dim > MAX_GRID_DIM * MAX_THREADS_PER_BLOCK:
            raise KernelConfigError(f"Invalid tensor dim: {new_dim}")

        self._tensor = TensorDescriptor(
            name=self._tensor.name,
            dim=new_dim,
            dtype_bytes=self._tensor.dtype_bytes,
            ndim=self._tensor.ndim,
        )
        if self._block_size > 0:
            self._recompute_grid()
        return self.get_config()

    # ── Queries ─────────────────────────────────────────────────

    @property
    def total_shared_memory(self) -> int:
        return sum(a.size_bytes for a in self._shared_mem_allocations)

    @property
    def is_configured(self) -> bool:
        return self._tensor is not None and self._block_size > 0

    def get_config(self) -> GridConfig:
        """Return the current launch configuration as an immutable snapshot."""
        if not self.is_configured:
            raise KernelConfigError("Kernel not yet configured")
        return GridConfig(
            block_size=self._block_size,
            num_blocks=self._num_blocks,
            threads_per_block=self._threads_per_block,
            elements_per_thread=self._elements_per_thread,
            shared_memory_bytes=self.total_shared_memory,
            tensor_dim=self._tensor.dim,
        )

    def validate(self) -> list[str]:
        """Check all invariants, return list of violations (empty = good)."""
        issues = []
        if not self.is_configured:
            issues.append("Kernel not configured")
            return issues

        config = self.get_config()
        if config.coverage < config.tensor_dim:
            issues.append(
                f"Incomplete coverage: grid covers {config.coverage} elements "
                f"but tensor has {config.tensor_dim}"
            )
        if config.shared_memory_bytes > self._max_shared_memory:
            issues.append(
                f"Shared memory {config.shared_memory_bytes}B exceeds "
                f"limit {self._max_shared_memory}B"
            )
        if config.threads_per_block > self._max_threads:
            issues.append(
                f"Threads per block {config.threads_per_block} exceeds "
                f"limit {self._max_threads}"
            )
        return issues

    def launch(self) -> GridConfig:
        """Validate and 'launch' the kernel. Returns the config used.

        In real code this would call into the Triton runtime. Here we
        just enforce the invariants and record the launch.
        """
        issues = self.validate()
        if issues:
            raise KernelConfigError(
                f"Cannot launch kernel: {'; '.join(issues)}"
            )
        self._launch_count += 1
        return self.get_config()

    # ── Internals ───────────────────────────────────────────────

    def _recompute_grid(self) -> None:
        """Recalculate num_blocks to cover the tensor.

        This is the critical operation: ceil(tensor_dim / block_size).
        Getting this wrong means silent data loss.
        """
        assert self._tensor is not None
        assert self._block_size > 0
        self._num_blocks = math.ceil(self._tensor.dim / self._block_size)
        if self._num_blocks > MAX_GRID_DIM:
            raise KernelConfigError(
                f"Grid requires {self._num_blocks} blocks, exceeding "
                f"max grid dim {MAX_GRID_DIM}"
            )

    def __repr__(self) -> str:
        if not self.is_configured:
            return "KernelLauncher(unconfigured)"
        c = self.get_config()
        return (
            f"KernelLauncher(tensor={self._tensor.name}[{c.tensor_dim}], "
            f"grid={c.num_blocks}x{c.block_size}, "
            f"threads={c.threads_per_block}, "
            f"smem={c.shared_memory_bytes}B, "
            f"launches={self._launch_count})"
        )
