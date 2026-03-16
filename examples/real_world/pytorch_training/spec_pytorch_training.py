"""PyTorch Training Loop Spec — configuration and checkpoint safety.

Proves:
- Epochs completed never exceeds max_epochs
- Learning rate stays within bounds after scaling
- Batch size is always at least 1
- Checkpoints happen before the interval is exceeded
- steps_since_checkpoint never exceeds checkpoint_interval
"""

from praxis import Spec, invariant, transition, And
from praxis.types import Nat, BoundedInt, BoundedFloat
from praxis.decorators import require


class TrainingLoopSpec(Spec):
    """PyTorch training loop with LR scheduling and checkpoint management."""

    epochs_completed: Nat
    max_epochs: BoundedInt[1, 10000]
    batch_size: BoundedInt[1, 4096]
    learning_rate: BoundedFloat[0.0, 10.0]
    grad_clip_threshold: BoundedFloat[0.0, 100.0]
    checkpoint_interval: BoundedInt[1, 1000]
    steps_since_checkpoint: Nat

    @invariant
    def training_not_overrun(self):
        """Never train past max_epochs."""
        return self.epochs_completed <= self.max_epochs

    @invariant
    def lr_non_negative(self):
        """Learning rate is never negative."""
        return self.learning_rate >= 0

    @invariant
    def batch_size_positive(self):
        """Batch size is always at least 1."""
        return self.batch_size >= 1

    @invariant
    def checkpoint_interval_bounded(self):
        """Checkpoint interval <= max_epochs guarantees at least one checkpoint."""
        return self.checkpoint_interval <= self.max_epochs

    @invariant
    def checkpoint_not_overdue(self):
        """Steps since last checkpoint never exceeds the interval."""
        return self.steps_since_checkpoint <= self.checkpoint_interval

    @transition
    def train_step(self):
        """Execute one training step."""
        require(self.steps_since_checkpoint + 1 <= self.checkpoint_interval)
        self.steps_since_checkpoint += 1

    @transition
    def checkpoint(self):
        """Save a checkpoint and reset the counter."""
        self.steps_since_checkpoint = 0

    @transition
    def complete_epoch(self):
        """Finish an epoch."""
        require(self.epochs_completed + 1 <= self.max_epochs)
        self.epochs_completed += 1

    @transition
    def scale_lr(self, factor: BoundedFloat[0.01, 2.0]):
        """Scale learning rate by a factor (warmup, decay, etc.)."""
        require(self.learning_rate * factor <= 10.0)
        require(self.learning_rate * factor >= 0.0)
        self.learning_rate = self.learning_rate * factor

    @transition
    def update_batch_size(self, new_size: BoundedInt[1, 4096]):
        """Change batch size (e.g., gradient accumulation adjustment)."""
        require(new_size >= 1)
        self.batch_size = new_size
