"""PyTorch training infrastructure — config, checkpointing, and LR scheduling.

A training harness that manages learning rate schedules (warmup + cosine decay),
gradient clipping, and checkpoint persistence. Designed to be the kind of code
an agent writes when you say "set up training" — the kind that works on the
happy path and silently loses your model on the sad one.

Does not import torch. This is pure configuration and orchestration logic
that would wrap torch training loops in production.
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class TrainingConfig:
    """Training hyperparameters and infrastructure settings.

    These are the knobs that an agent loves to tune and a human
    rarely double-checks until something goes wrong at 3am.
    """

    max_epochs: int = 100
    batch_size: int = 32
    learning_rate: float = 1e-3
    min_lr: float = 1e-6
    warmup_epochs: int = 5
    grad_clip_threshold: float = 1.0
    checkpoint_interval: int = 10  # epochs between checkpoints
    checkpoint_dir: str = "./checkpoints"
    log_interval: int = 100  # steps between log lines

    def __post_init__(self):
        if self.max_epochs < 1:
            raise ValueError(f"max_epochs must be >= 1, got {self.max_epochs}")
        if self.batch_size < 1:
            raise ValueError(f"batch_size must be >= 1, got {self.batch_size}")
        if self.learning_rate < 0:
            raise ValueError(f"learning_rate must be >= 0, got {self.learning_rate}")
        if self.checkpoint_interval < 1:
            raise ValueError(f"checkpoint_interval must be >= 1, got {self.checkpoint_interval}")
        if self.checkpoint_interval > self.max_epochs:
            raise ValueError(
                f"checkpoint_interval ({self.checkpoint_interval}) > max_epochs ({self.max_epochs}). "
                f"No checkpoint would ever be saved."
            )
        if self.warmup_epochs >= self.max_epochs:
            raise ValueError(
                f"warmup_epochs ({self.warmup_epochs}) >= max_epochs ({self.max_epochs}). "
                f"Training would never leave warmup."
            )


@dataclass
class TrainingState:
    """Mutable training state that survives checkpoints."""

    epochs_completed: int = 0
    global_step: int = 0
    steps_since_checkpoint: int = 0
    current_lr: float = 0.0
    best_loss: float = float("inf")
    total_training_time: float = 0.0


class LRScheduler:
    """Warmup + cosine decay learning rate schedule.

    Linear warmup for the first warmup_epochs, then cosine decay
    down to min_lr over the remaining epochs.
    """

    def __init__(self, config: TrainingConfig):
        self.base_lr = config.learning_rate
        self.min_lr = config.min_lr
        self.warmup_epochs = config.warmup_epochs
        self.max_epochs = config.max_epochs

    def get_lr(self, epoch: int) -> float:
        """Compute LR for a given epoch."""
        if epoch < 0:
            return 0.0

        # Warmup phase: linear ramp from 0 to base_lr
        if epoch < self.warmup_epochs:
            if self.warmup_epochs == 0:
                return self.base_lr
            return self.base_lr * (epoch + 1) / self.warmup_epochs

        # Cosine decay phase
        decay_epochs = self.max_epochs - self.warmup_epochs
        if decay_epochs <= 0:
            return self.base_lr

        progress = (epoch - self.warmup_epochs) / decay_epochs
        cosine_decay = 0.5 * (1 + math.cos(math.pi * progress))
        return self.min_lr + (self.base_lr - self.min_lr) * cosine_decay


class CheckpointManager:
    """Manages checkpoint saving and loading.

    Keeps track of the best model and periodic checkpoints.
    The critical property: steps_since_checkpoint is always reset
    when a checkpoint is saved. If it isn't, the interval counter
    drifts and you stop getting checkpoints — which you only discover
    when the job crashes at epoch 847 and your last save was epoch 12.
    """

    def __init__(self, config: TrainingConfig):
        self.checkpoint_dir = Path(config.checkpoint_dir)
        self.checkpoint_interval = config.checkpoint_interval
        self.max_keep = 3

    def should_checkpoint(self, state: TrainingState) -> bool:
        """Check if we should save a checkpoint now."""
        return state.steps_since_checkpoint >= self.checkpoint_interval

    def save(self, state: TrainingState, metrics: dict[str, float] | None = None) -> Path:
        """Save a checkpoint. Resets steps_since_checkpoint."""
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "epochs_completed": state.epochs_completed,
            "global_step": state.global_step,
            "best_loss": state.best_loss,
            "total_training_time": state.total_training_time,
            "current_lr": state.current_lr,
            "saved_at": time.time(),
        }
        if metrics:
            checkpoint["metrics"] = metrics

        path = self.checkpoint_dir / f"checkpoint_epoch_{state.epochs_completed}.json"
        with open(path, "w") as f:
            json.dump(checkpoint, f, indent=2)

        # Reset the counter — this is the critical line
        state.steps_since_checkpoint = 0

        self._cleanup_old_checkpoints()
        return path

    def load_latest(self) -> dict[str, Any] | None:
        """Load the most recent checkpoint, if any."""
        if not self.checkpoint_dir.exists():
            return None

        checkpoints = sorted(
            self.checkpoint_dir.glob("checkpoint_epoch_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not checkpoints:
            return None

        with open(checkpoints[0]) as f:
            return json.load(f)

    def _cleanup_old_checkpoints(self) -> None:
        """Keep only the most recent checkpoints."""
        if not self.checkpoint_dir.exists():
            return

        checkpoints = sorted(
            self.checkpoint_dir.glob("checkpoint_epoch_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for old in checkpoints[self.max_keep:]:
            old.unlink()


class GradientClipper:
    """Gradient clipping by global norm."""

    def __init__(self, max_norm: float):
        if max_norm <= 0:
            raise ValueError(f"max_norm must be positive, got {max_norm}")
        self.max_norm = max_norm

    def clip(self, grad_norms: list[float]) -> tuple[list[float], float]:
        """Clip gradients by global norm. Returns clipped norms and scale factor."""
        total_norm = math.sqrt(sum(n * n for n in grad_norms)) if grad_norms else 0.0

        if total_norm == 0:
            return grad_norms, 1.0

        clip_coef = self.max_norm / total_norm
        if clip_coef >= 1.0:
            return grad_norms, 1.0

        clipped = [n * clip_coef for n in grad_norms]
        return clipped, clip_coef


class Trainer:
    """Orchestrates training: LR schedule, gradient clipping, checkpointing.

    Usage:
        config = TrainingConfig(max_epochs=100, batch_size=64)
        trainer = Trainer(config)

        for epoch in trainer.epochs():
            for batch in dataloader:
                loss = model(batch)
                trainer.step(loss_value=loss.item(), grad_norms=[...])
            trainer.end_epoch(val_loss=val_loss)
    """

    def __init__(self, config: TrainingConfig):
        self.config = config
        self.state = TrainingState(current_lr=config.learning_rate)
        self.scheduler = LRScheduler(config)
        self.clipper = GradientClipper(config.grad_clip_threshold)
        self.checkpointer = CheckpointManager(config)

        # Load existing checkpoint if available
        existing = self.checkpointer.load_latest()
        if existing:
            self.state.epochs_completed = existing["epochs_completed"]
            self.state.global_step = existing["global_step"]
            self.state.best_loss = existing["best_loss"]
            self.state.total_training_time = existing.get("total_training_time", 0.0)

    def epochs(self) -> range:
        """Iterator over remaining epochs."""
        return range(self.state.epochs_completed, self.config.max_epochs)

    def step(self, loss_value: float, grad_norms: list[float]) -> dict[str, float]:
        """Execute one training step. Returns step metrics."""
        clipped_norms, clip_scale = self.clipper.clip(grad_norms)

        self.state.global_step += 1
        self.state.steps_since_checkpoint += 1

        return {
            "loss": loss_value,
            "lr": self.state.current_lr,
            "grad_norm": math.sqrt(sum(n * n for n in grad_norms)) if grad_norms else 0.0,
            "clip_scale": clip_scale,
            "global_step": self.state.global_step,
        }

    def end_epoch(self, val_loss: float | None = None) -> dict[str, Any]:
        """End an epoch: update LR, maybe checkpoint, track best loss."""
        self.state.epochs_completed += 1
        self.state.current_lr = self.scheduler.get_lr(self.state.epochs_completed)

        result: dict[str, Any] = {
            "epoch": self.state.epochs_completed,
            "lr": self.state.current_lr,
        }

        if val_loss is not None and val_loss < self.state.best_loss:
            self.state.best_loss = val_loss
            result["new_best"] = True

        if self.checkpointer.should_checkpoint(self.state):
            path = self.checkpointer.save(self.state)
            result["checkpoint"] = str(path)

        return result
