# Task Queue

## The Problem

Task queues are the backbone of async job processing — background email sends, image processing, report generation. The critical invariant is conservation: every submitted task must eventually be pending, running, or completed. If `pending + running + completed != total_submitted`, tasks have been silently lost or double-counted.

The second invariant is worker bounds: running tasks should never exceed the worker pool size. Without this, the system spawns unbounded concurrent work, exhausting CPU, memory, or external service rate limits. This bug typically hides behind a `if workers_available > 0` check that races with concurrent task starts.

## The Implementation

`task_queue.py` — A `TaskQueue` using:
- **`queue.PriorityQueue`** for priority-based scheduling
- **`threading`** for worker pool management
- **`dataclasses`** for `Task` with lifecycle tracking

```python
class TaskQueue:
    def submit(self, task: Task) -> str
    def start_workers(self) -> None
    def shutdown(self, wait: bool = True) -> None
    def process_one(self, task_id: str) -> Any  # for testing
```

Features retry logic (configurable max_retries), dead letter queue for permanently failed tasks, and task state tracking (PENDING → RUNNING → COMPLETED/FAILED/DEAD).

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/task_queue/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    queue,
    TaskQueueSpec,
    state_extractor=lambda self: {
        'pending': self._pending_count,
        'running': self._running_count,
        'completed': self._completed_count,
        'workers': self.max_workers,
        'total_submitted': self._total_submitted,
    },
    operations=[
        lambda q: q.submit(task),
        lambda q: q.process_one(task_id),
    ],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    TaskQueue,
    TaskQueueSpec,
    state_extractor=lambda self: {
        'pending': self._pending_count, 'running': self._running_count,
        'completed': self._completed_count, 'workers': self.max_workers,
        'total_submitted': self._total_submitted,
    },
    methods=["submit", "_execute_task"],
    mode="log",
)
```

### 4. Per-method decorators (legacy, still supported)

The `submit()` and `_execute_task()` methods are currently decorated with `@runtime_guard`:

```python
@runtime_guard(TaskQueueSpec, state_extractor=lambda self: {
    'pending': self._pending_count,
    'running': self._running_count,
    'completed': self._completed_count,
    'workers': self.max_workers,
    'total_submitted': self._total_submitted,
})
def submit(self, task: Task) -> str: ...
```

After every `submit` or `_execute_task` call, the guard verifies that `pending + running + completed == total_submitted` (conservation) and `running <= workers` (worker bounds). An `AssertionError` fires immediately if a task is lost, double-counted, or too many tasks run concurrently.

## The Spec

1. **`conservation`**: `pending + running + completed == total_submitted`
2. **`running_bounded_by_workers`**: `running <= workers`

## The Bug Praxis Catches

In `broken/spec_task_queue.py`, `start_task` doesn't check the worker limit:

```python
@transition
def start_task(self, dummy: BoundedInt[0, 0]):
    require(self.pending > 0)
    # Missing: require(self.running + 1 <= self.workers)
    self.pending -= 1
    self.running += 1
```

Praxis finds: 1 worker, 2 pending tasks — start both, running=2 exceeds workers=1.

## Run It

```bash
pytest examples/real_world/task_queue/ -v
praxis check examples/real_world/task_queue/
praxis check examples/real_world/task_queue/broken/
```
