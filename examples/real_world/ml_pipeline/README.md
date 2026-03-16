# ML Training Pipeline

## The Problem

GPU clusters are expensive — a single A100 node costs $10-30/hour. When a training job scheduler overcommits VRAM, the GPU kernel crashes, killing not just the offending job but every job sharing that GPU. Hours of training progress are lost, checkpoints may be corrupted, and the cluster needs manual intervention to recover.

The bug is always the same: the scheduler checks VRAM availability, then allocates, but the check and allocation aren't atomic. Or worse, the scheduler checks per-GPU availability but not total node VRAM when a job spans multiple GPUs. Under low utilization, the race never triggers. Under production load with back-to-back job submissions, it's inevitable.

## The Implementation

`scheduler.py` — A `TrainingScheduler` using `dataclasses` for job and node tracking:

```python
class TrainingScheduler:
    def add_node(self, node_id: str, vram_gb: int) -> None
    def submit_job(self, job: TrainingJob) -> str
    def schedule_job(self, job_id: str, node_id: str) -> None
    def preempt_job(self, job_id: str) -> None
    def scale_learning_rate(self, job_id: str, factor: float) -> None
```

Features VRAM tracking per node, job lifecycle management, and learning rate scheduling.

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/ml_pipeline/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    scheduler,
    TrainingSchedulerSpec,
    state_extractor=lambda self: {
        'vram_capacity': self._last_affected_node.total_vram_gb,
        'vram_allocated': self._last_affected_node.allocated_vram_gb,
        'active_jobs': len(self._last_affected_node.active_jobs),
        'lr': 0.001, 'batch_size': 32,
    },
    operations=[
        lambda s: s.schedule_job(job_id, node_id),
        lambda s: s.preempt_job(job_id),
    ],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    TrainingScheduler,
    TrainingSchedulerSpec,
    state_extractor=lambda self: {
        'vram_capacity': self._last_affected_node.total_vram_gb,
        'vram_allocated': self._last_affected_node.allocated_vram_gb,
        'active_jobs': len(self._last_affected_node.active_jobs),
        'lr': 0.001, 'batch_size': 32,
    },
    methods=["schedule_job", "preempt_job", "complete_job"],
    mode="log",
)
```

### 4. Per-method decorators (legacy, still supported)

The `schedule_job()`, `preempt_job()`, and `complete_job()` methods are currently decorated with `@runtime_guard`:

```python
@runtime_guard(TrainingSchedulerSpec, state_extractor=lambda self: {
    'vram_capacity': self._last_affected_node.total_vram_gb,
    'vram_allocated': self._last_affected_node.allocated_vram_gb,
    'active_jobs': len(self._last_affected_node.active_jobs),
    'lr': 0.001, 'batch_size': 32,
})
def schedule_job(self, job_id: str, node_id: str) -> None: ...
```

After every schedule, preemption, or completion, the guard verifies that VRAM allocation never exceeds capacity and all counters stay non-negative. An `AssertionError` fires immediately if GPU memory is overcommitted.

## The Spec

1. **`vram_bounded`**: `vram_allocated <= vram_capacity` — never overcommit GPU memory
2. **`resources_non_negative`**: All counters stay non-negative

## The Bug Praxis Catches

In `broken/spec_training.py`, `submit_job` is missing the VRAM check:

```python
@transition
def submit_job(self, vram_req: BoundedInt[1, 80]):
    # Missing: require(self.vram_allocated + vram_req <= self.vram_capacity)
    self.vram_allocated += vram_req
```

Praxis finds: node with 1GB capacity, allocate 80GB — instant VRAM overcommit.

## Run It

```bash
pytest examples/real_world/ml_pipeline/ -v
praxis check examples/real_world/ml_pipeline/
praxis check examples/real_world/ml_pipeline/broken/
```
