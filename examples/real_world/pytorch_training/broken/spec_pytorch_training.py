"""Broken PyTorch Training Loop Spec — checkpoint doesn't reset counter.

The bug: the checkpoint transition doesn't reset steps_since_checkpoint,
so the counter grows without bound and eventually exceeds checkpoint_interval.
This models a real bug where the checkpoint save path runs but the tracking
state isn't updated — the system thinks it's checkpointing, but the next
checkpoint never triggers because the counter is stale.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import Nat, BoundedInt, BoundedFloat
from praxis.decorators import require


class BrokenTrainingLoopSpec(Spec):
    """Training loop where checkpoint forgets to reset the step counter."""

    epochs_completed: Nat
    max_epochs: BoundedInt[1, 10000]
    batch_size: BoundedInt[1, 4096]
    learning_rate: BoundedFloat[0.0, 10.0]
    grad_clip_threshold: BoundedFloat[0.0, 100.0]
    checkpoint_interval: BoundedInt[1, 1000]
    steps_since_checkpoint: Nat

    @invariant
    def training_not_overrun(self):
        return self.epochs_completed <= self.max_epochs

    @invariant
    def lr_non_negative(self):
        return self.learning_rate >= 0

    @invariant
    def batch_size_positive(self):
        return self.batch_size >= 1

    @invariant
    def checkpoint_interval_bounded(self):
        return self.checkpoint_interval <= self.max_epochs

    @invariant
    def checkpoint_not_overdue(self):
        """Steps since last checkpoint never exceeds the interval."""
        return self.steps_since_checkpoint <= self.checkpoint_interval

    @transition
    def train_step(self):
        require(self.steps_since_checkpoint + 1 <= self.checkpoint_interval)
        self.steps_since_checkpoint += 1

    @transition
    def checkpoint(self):
        """BUG: Missing self.steps_since_checkpoint = 0"""
        # Should have: self.steps_since_checkpoint = 0
        # Without it, train_step can push steps_since_checkpoint past
        # checkpoint_interval after enough steps.
        pass

    @transition
    def complete_epoch(self):
        require(self.epochs_completed + 1 <= self.max_epochs)
        self.epochs_completed += 1

    @transition
    def scale_lr(self, factor: BoundedFloat[0.01, 2.0]):
        require(self.learning_rate * factor <= 10.0)
        require(self.learning_rate * factor >= 0.0)
        self.learning_rate = self.learning_rate * factor

    @transition
    def update_batch_size(self, new_size: BoundedInt[1, 4096]):
        require(new_size >= 1)
        self.batch_size = new_size
