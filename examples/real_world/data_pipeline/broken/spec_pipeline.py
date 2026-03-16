"""Broken Data Pipeline Spec -- produce transition missing capacity check.

This spec is identical to the correct one except that the ``produce``
transition does NOT verify ``queue_size + count <= capacity`` before adding
messages.  Without this backpressure guard, a producer can push the queue
past its capacity, violating the ``bounded`` invariant.

Praxis will find a counterexample: a sequence of produce calls that drives
``queue_size`` above ``capacity``, proving the invariant is unreachable
without the guard.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, Nat
from praxis.decorators import require


class BrokenBoundedQueueSpec(Spec):
    """Bounded buffer where produce forgets the capacity check."""

    queue_size: BoundedInt[0, 10000]
    capacity: BoundedInt[1, 10000]
    produced: Nat
    consumed: Nat

    @invariant
    def bounded(self):
        """Queue never exceeds capacity."""
        return self.queue_size <= self.capacity

    @invariant
    def non_negative(self):
        """Queue size is never negative."""
        return self.queue_size >= 0

    @invariant
    def no_phantom_reads(self):
        """Can't consume more than was produced."""
        return self.consumed <= self.produced

    @invariant
    def queue_consistent(self):
        """Queue size = produced - consumed."""
        return self.queue_size == self.produced - self.consumed

    @transition
    def produce(self, count: BoundedInt[1, 100]):
        """BUG: No backpressure -- missing capacity check."""
        # Missing: require(self.queue_size + count <= self.capacity)
        self.queue_size += count
        self.produced += count

    @transition
    def consume(self, count: BoundedInt[1, 100]):
        """Remove messages from the queue."""
        require(self.queue_size >= count)
        self.queue_size -= count
        self.consumed += count
