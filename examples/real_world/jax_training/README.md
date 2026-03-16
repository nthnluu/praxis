# JAX Distributed Training

## The Problem

Distributed training on JAX (or PyTorch, or anything multi-device) has a configuration surface area that's quietly enormous. You've got device meshes, sharding strategies, micro-batch sizes, gradient accumulation steps, VRAM budgets, and learning rate schedules. Each one is a scalar. Together they form a system of constraints that your training run silently assumes are satisfied.

When they're not, the failure modes are brutal:

- **VRAM overcommit**: Two jobs get scheduled, total allocation exceeds physical memory, CUDA OOM kills both. Hours of checkpoint progress gone. I've seen this take down a 64-GPU cluster at 2am because the scheduler didn't do the capacity check atomically.
- **Batch size math drift**: Someone halves `micro_batch_size` to fit in VRAM but forgets to double `accumulation_steps`. The effective batch size changes. The loss curve looks fine for 10k steps. Then it diverges. Two days of debugging before someone checks the arithmetic.
- **Shard oversubscription**: Request 8-way model parallelism on a 4-device node. JAX throws a cryptic XLA error about mesh shapes. If you're lucky. If you're not, it silently falls back to a different strategy and you wonder why throughput halved.

These aren't exotic bugs. They're configuration typos that unit tests don't catch because each value looks reasonable in isolation. The bug is in the *relationship* between values.

## The Implementation

`jax_training.py` — A `DistributedTrainer` class using dataclasses (no JAX dependency, but models the concepts accurately):

```python
class DistributedTrainer:
    def add_device(self, device_id: str, vram_gb: int) -> None
    def submit_job(self, job: TrainingJob) -> str
    def release_job(self, job_id: str) -> None
    def scale_batch(self, job_id: str, new_micro: int, new_accum: int) -> None
    def update_lr(self, job_id: str, factor: float) -> None
    def reshard(self, job_id: str, new_shards: int, ...) -> None
```

Includes `TrainingConfig` (batch math, LR, sharding strategy), `DeviceSpec` (per-device VRAM tracking), and `TrainingJob` (lifecycle management).

## The Spec

`spec_jax_training.py` models the state that matters — the numbers that have to stay consistent:

1. **`vram_not_overcommitted`**: `total_vram_allocated <= 5120` — cluster-wide VRAM budget. No job submission can push total allocation past what's physically available.
2. **`vram_non_negative`**: Can't free more VRAM than you've allocated.
3. **`lr_positive`**: Learning rate stays positive through any schedule of warmup/decay steps.
4. **`shards_fit_devices`**: `num_shards <= num_devices` — can't shard across more devices than exist.
5. **`batch_sizes_positive`**: All batch dimensions are always >= 1.

### A note on nonlinear arithmetic

The natural invariant is `accumulation_steps * micro_batch_size == effective_batch_size`. But Z3 hates multiplication of two unconstrained variables — it's nonlinear integer arithmetic and the solver either times out or returns unknown. So we sidestep it: `effective_batch_size` is tracked as a pre-computed value, and the `scale_batch` transition accepts all three values with guards ensuring the new effective size is at least as large as each component. The real implementation computes and validates the multiplication in Python. The spec verifies the properties that Z3 *can* reason about. This is a deliberate tradeoff — verify what you can, validate the rest at runtime.

## The Bug Praxis Catches

In `broken/spec_jax_training.py`, `submit_job` allocates VRAM without checking capacity:

```python
@transition
def submit_job(self, vram_req: BoundedInt[1, 80]):
    """BUG: No capacity check."""
    # Missing: require(self.total_vram_allocated + vram_req <= 5120)
    self.total_vram_allocated += vram_req
```

Praxis finds a counterexample: start with `total_vram_allocated` near the cap (say, 5100 GiB), submit a job requesting 80 GiB, and the invariant `total_vram_allocated <= 5120` breaks. That's the exact sequence that causes the 2am page — the scheduler said "yes" when it should have said "wait."

## Run It

```bash
# Verify the correct spec (should pass)
praxis check examples/real_world/jax_training/

# Verify the broken spec (should find the VRAM overcommit bug)
praxis check examples/real_world/jax_training/broken/
```
