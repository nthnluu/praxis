# PyTorch Training Infrastructure

## The Problem

Training runs are expensive. An 8-GPU job running for 72 hours costs real money, and the failure modes are silent. The LR schedule is slightly wrong? Your model converges to a worse minimum and you don't know for weeks. The checkpoint interval is misconfigured? You find out when the job OOMs at hour 68 and your last save was hour 3. Batch size set to zero by a config typo? Instant crash — at least that one's obvious.

The deeper issue: training infrastructure is exactly the kind of "glue code" that agents love to generate. Config dataclasses, checkpoint managers, LR schedulers. It all looks right. It passes unit tests because the tests check the happy path. But the invariants that actually matter — checkpoints happen on schedule, learning rate stays sane, epochs don't overrun — those live in the gaps between functions, not inside them.

## The Implementation

`pytorch_training.py` — A training harness with:
- **`TrainingConfig`** — hyperparameters with validation
- **`LRScheduler`** — warmup + cosine decay schedule
- **`CheckpointManager`** — periodic saves with cleanup, resets `steps_since_checkpoint` on save
- **`GradientClipper`** — global norm clipping
- **`Trainer`** — orchestrates the training loop

```python
config = TrainingConfig(max_epochs=100, batch_size=64, checkpoint_interval=10)
trainer = Trainer(config)

for epoch in trainer.epochs():
    for batch in dataloader:
        metrics = trainer.step(loss_value=loss.item(), grad_norms=[...])
    trainer.end_epoch(val_loss=val_loss)
```

No torch import. This is the orchestration layer — the part that manages state transitions, not tensor math.

## The Spec

1. **`training_not_overrun`**: `epochs_completed <= max_epochs`
2. **`lr_non_negative`**: `learning_rate >= 0` after any scaling
3. **`batch_size_positive`**: `batch_size >= 1` always
4. **`checkpoint_interval_bounded`**: `checkpoint_interval <= max_epochs` — guarantees at least one checkpoint per run
5. **`checkpoint_not_overdue`**: `steps_since_checkpoint <= checkpoint_interval` — the one that catches real bugs

## The Bug Praxis Catches

In `broken/spec_pytorch_training.py`, the `checkpoint` transition doesn't reset `steps_since_checkpoint`:

```python
@transition
def checkpoint(self):
    """BUG: Missing self.steps_since_checkpoint = 0"""
    pass
```

Without the reset, the counter keeps climbing. After enough `train_step` calls, `steps_since_checkpoint` exceeds `checkpoint_interval`, violating `checkpoint_not_overdue`.

This models a real bug: the checkpoint function writes the file to disk but doesn't update the internal counter. The system thinks it's checkpointing on schedule. It isn't. The next checkpoint never triggers because the counter is already past the threshold. Your 72-hour job crashes at hour 68 and your last save was hour 3.

Praxis finds this immediately — a counterexample showing the exact sequence of transitions that breaks the invariant.

## Run It

```bash
# Correct spec — all invariants hold
praxis check examples/real_world/pytorch_training/

# Broken spec — checkpoint_not_overdue is violated
praxis check examples/real_world/pytorch_training/broken/
```
