"""Broken Triton Kernel Spec — configure_kernel doesn't ensure full coverage.

Bug: configure_kernel sets block_size and num_blocks but never checks
that their product covers tensor_dim. This means tail elements of the
tensor are silently skipped — no error, just wrong results.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, ByteSize
from praxis.decorators import require


class BrokenTritonKernelSpec(Spec):
    """GPU kernel launch configuration — missing coverage check."""

    tensor_dim: BoundedInt[1, 65536]
    block_size: BoundedInt[1, 1024]
    num_blocks: BoundedInt[1, 65536]
    shared_memory_per_block: ByteSize[0, 49152]
    max_shared_memory: ByteSize[1, 49152]
    threads_per_block: BoundedInt[1, 1024]
    elements_per_thread: BoundedInt[1, 64]

    @invariant
    def full_coverage(self):
        """Grid must cover every tensor element."""
        return self.num_blocks * self.block_size >= self.tensor_dim

    @invariant
    def shared_memory_bounded(self):
        return self.shared_memory_per_block <= self.max_shared_memory

    @invariant
    def threads_bounded(self):
        return self.threads_per_block <= 1024

    @transition
    def configure_kernel(
        self,
        new_block_size: BoundedInt[1, 1024],
        new_num_blocks: BoundedInt[1, 65536],
    ):
        """BUG: No check that new_num_blocks * new_block_size >= tensor_dim.

        An agent could set block_size=32, num_blocks=1 for a tensor of
        65536 elements. Only the first 32 elements get processed.
        """
        # Missing: require(new_num_blocks * new_block_size >= self.tensor_dim)
        self.block_size = new_block_size
        self.num_blocks = new_num_blocks

    @transition
    def allocate_shared_memory(
        self,
        amount: ByteSize[0, 49152],
    ):
        require(amount <= self.max_shared_memory)
        self.shared_memory_per_block = amount

    @transition
    def set_thread_config(
        self,
        threads: BoundedInt[1, 1024],
        elems: BoundedInt[1, 64],
    ):
        require(threads <= 1024)
        self.threads_per_block = threads
        self.elements_per_thread = elems

    @transition
    def resize_tensor(
        self,
        new_dim: BoundedInt[1, 65536],
        new_num_blocks: BoundedInt[1, 65536],
    ):
        """Also broken: no coverage check on resize either."""
        # Missing: require(new_num_blocks * self.block_size >= new_dim)
        self.tensor_dim = new_dim
        self.num_blocks = new_num_blocks
