"""Triton Kernel Launch Spec — GPU kernel configuration safety.

Proves:
- Kernel grid covers the entire tensor (num_blocks * block_size >= tensor_dim)
- Shared memory per block stays within hardware limits
- Threads per block respects GPU maximum (1024)

The coverage invariant uses multiplication (nonlinear arithmetic), but Z3
handles it fine for these bounded integers. Every transition that touches
block_size, num_blocks, or tensor_dim must maintain coverage.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, ByteSize
from praxis.decorators import require


class TritonKernelSpec(Spec):
    """GPU kernel launch configuration with resource bounds."""

    tensor_dim: BoundedInt[1, 65536]                # Elements to process
    block_size: BoundedInt[1, 1024]                  # Elements per block (tile width)
    num_blocks: BoundedInt[1, 65536]                 # Grid size
    shared_memory_per_block: ByteSize[0, 49152]       # Bytes of shared mem used
    max_shared_memory: ByteSize[1, 49152]             # Hardware limit (48KB typical)
    threads_per_block: BoundedInt[1, 1024]           # Threads launched per block
    elements_per_thread: BoundedInt[1, 64]           # Work per thread

    @invariant
    def full_coverage(self):
        """Grid must cover every tensor element. Without this,
        tail elements are silently skipped — no crash, just wrong results."""
        return self.num_blocks * self.block_size >= self.tensor_dim

    @invariant
    def shared_memory_bounded(self):
        """Shared memory usage never exceeds hardware limit."""
        return self.shared_memory_per_block <= self.max_shared_memory

    @invariant
    def threads_bounded(self):
        """Threads per block respects GPU maximum."""
        return self.threads_per_block <= 1024

    @transition
    def configure_kernel(
        self,
        new_block_size: BoundedInt[1, 1024],
        new_num_blocks: BoundedInt[1, 65536],
    ):
        """Set block size and grid dimensions for a kernel launch.

        The key require(): new_num_blocks * new_block_size must cover
        every element of the tensor. Without this, the tail elements
        are never processed — silent data corruption.
        """
        require(new_num_blocks * new_block_size >= self.tensor_dim)
        self.block_size = new_block_size
        self.num_blocks = new_num_blocks

    @transition
    def allocate_shared_memory(
        self,
        amount: ByteSize[0, 49152],
    ):
        """Set shared memory usage for a block."""
        require(amount <= self.max_shared_memory)
        self.shared_memory_per_block = amount

    @transition
    def set_thread_config(
        self,
        threads: BoundedInt[1, 1024],
        elems: BoundedInt[1, 64],
    ):
        """Configure threads per block and elements per thread."""
        require(threads <= 1024)
        self.threads_per_block = threads
        self.elements_per_thread = elems

    @transition
    def resize_tensor(
        self,
        new_dim: BoundedInt[1, 65536],
        new_num_blocks: BoundedInt[1, 65536],
    ):
        """Change tensor dimensions and recompute grid to maintain coverage.

        When the input tensor changes size, the grid must be recalculated.
        Forgetting this recomputation is a common source of OOB access.
        """
        require(new_num_blocks * self.block_size >= new_dim)
        self.tensor_dim = new_dim
        self.num_blocks = new_num_blocks
