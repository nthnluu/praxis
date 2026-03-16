"""Task Queue Spec — priority task queue with worker management.

Proves:
- Pending + running + completed = total submitted
- Running tasks never exceed worker count
- Worker count is bounded
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, Nat
from praxis.decorators import require


class TaskQueueSpec(Spec):
    """Task queue with worker pool."""

    pending: Nat
    running: Nat
    completed: Nat
    workers: BoundedInt[1, 100]
    total_submitted: Nat

    @invariant
    def conservation(self):
        """pending + running + completed = total submitted."""
        return self.pending + self.running + self.completed == self.total_submitted

    @invariant
    def running_bounded_by_workers(self):
        """Can't run more tasks than workers available."""
        return self.running <= self.workers

    @invariant
    def non_negative(self):
        return And(self.pending >= 0, self.running >= 0, self.completed >= 0)

    @transition
    def submit_task(self):
        """Submit a new task to the queue."""
        require(self.pending + 1 <= 10000)
        require(self.total_submitted + 1 <= 100000)
        self.pending += 1
        self.total_submitted += 1

    @transition
    def start_task(self):
        """Pick up a pending task."""
        require(self.pending > 0)
        require(self.running + 1 <= self.workers)
        self.pending -= 1
        self.running += 1

    @transition
    def complete_task(self):
        """Mark a running task as completed."""
        require(self.running > 0)
        require(self.completed + 1 <= 100000)
        self.running -= 1
        self.completed += 1
