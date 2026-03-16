"""Broken task queue spec — start_task doesn't check worker limit.

Bug: start_task allows starting a task even when running >= workers,
violating the running_bounded_by_workers invariant.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, Nat
from praxis.decorators import require


class BrokenTaskQueueSpec(Spec):
    pending: Nat
    running: Nat
    completed: Nat
    workers: BoundedInt[1, 100]
    total_submitted: Nat

    @invariant
    def conservation(self):
        return self.pending + self.running + self.completed == self.total_submitted

    @invariant
    def running_bounded_by_workers(self):
        return self.running <= self.workers

    @transition
    def submit_task(self):
        require(self.pending + 1 <= 10000)
        require(self.total_submitted + 1 <= 100000)
        self.pending += 1
        self.total_submitted += 1

    @transition
    def start_task(self):
        """BUG: Missing require(self.running + 1 <= self.workers)."""
        require(self.pending > 0)
        # Missing: require(self.running + 1 <= self.workers)
        self.pending -= 1
        self.running += 1

    @transition
    def complete_task(self):
        require(self.running > 0)
        require(self.completed + 1 <= 100000)
        self.running -= 1
        self.completed += 1
