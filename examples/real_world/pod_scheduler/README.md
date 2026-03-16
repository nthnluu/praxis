# Pod Scheduler

## The Problem

Kubernetes pod scheduling must enforce hard resource limits. A pod requesting 4 CPU cores and 8GB RAM can only be placed on a node with that much available capacity. If the scheduler places it anyway, the kubelet will either reject the pod (causing a scheduling loop) or allow it and trigger OOM kills when actual usage exceeds physical memory.

The classic bug: the scheduler checks CPU availability but not memory (or vice versa). Under testing, pods request proportional CPU and memory, so a CPU-only check happens to also catch memory overcommit. In production, someone submits a memory-heavy job (ML inference: low CPU, high memory), and the scheduler places it on a node with plenty of CPU but insufficient RAM.

## The Implementation

`scheduler.py` — A `PodScheduler` with bin-packing scoring:

```python
class PodScheduler:
    def add_node(self, name: str, cpu: int, memory_mb: int) -> None
    def schedule_pod(self, pod: Pod) -> str  # returns node name
    def evict_pod(self, pod_name: str) -> None
    def cordon_node(self, name: str) -> None
    def drain_node(self, name: str) -> list[str]
```

Node scoring prefers tighter bin-packing (higher utilization nodes first) to minimize fragmentation.

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/pod_scheduler/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    scheduler,
    PodSchedulerSpec,
    state_extractor=lambda self: {
        'cpu_used': self._last_affected_node.cpu_allocated,
        'cpu_capacity': self._last_affected_node.cpu_capacity,
        'mem_used': self._last_affected_node.memory_allocated_mb,
        'mem_capacity': self._last_affected_node.memory_capacity_mb,
        'pod_count': self._last_affected_node.pod_count,
        'max_pods': self._last_affected_node.max_pods,
    },
    operations=[
        lambda s: s.schedule_pod(pod),
        lambda s: s.evict_pod(pod_name),
    ],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    PodScheduler,
    PodSchedulerSpec,
    state_extractor=lambda self: {
        'cpu_used': self._last_affected_node.cpu_allocated,
        'cpu_capacity': self._last_affected_node.cpu_capacity,
        'mem_used': self._last_affected_node.memory_allocated_mb,
        'mem_capacity': self._last_affected_node.memory_capacity_mb,
        'pod_count': self._last_affected_node.pod_count,
        'max_pods': self._last_affected_node.max_pods,
    },
    methods=["schedule_pod", "evict_pod"],
    mode="log",
)
```

### 4. Per-method decorators (legacy, still supported)

The `schedule_pod()` and `evict_pod()` methods are currently decorated with `@runtime_guard`:

```python
@runtime_guard(PodSchedulerSpec, state_extractor=lambda self: {
    'cpu_used': self._last_affected_node.cpu_allocated,
    'cpu_capacity': self._last_affected_node.cpu_capacity,
    'mem_used': self._last_affected_node.memory_allocated_mb,
    'mem_capacity': self._last_affected_node.memory_capacity_mb,
    'pod_count': self._last_affected_node.pod_count,
    'max_pods': self._last_affected_node.max_pods,
})
def schedule_pod(self, pod: Pod) -> str: ...
```

After every schedule or eviction, the guard verifies that CPU and memory allocations stay within capacity, and pod count stays within the limit. An `AssertionError` fires immediately if any resource is overcommitted.

## The Spec

1. **`cpu_bounded`**: `cpu_used <= cpu_capacity`
2. **`mem_bounded`**: `mem_used <= mem_capacity`
3. **`pods_bounded`**: `pod_count <= max_pods`

## The Bug Praxis Catches

In `broken/spec_pods.py`, `schedule_pod` checks CPU but not memory:

```python
@transition
def schedule_pod(self, cpu: BoundedInt[1, 16], mem: BoundedInt[1, 64]):
    require(self.cpu_used + cpu <= self.cpu_capacity)
    # Missing: require(self.mem_used + mem <= self.mem_capacity)
    require(self.pod_count + 1 <= self.max_pods)
    self.cpu_used += cpu
    self.mem_used += mem
```

Praxis finds: node with 1MB memory capacity, schedule a pod needing 64MB — memory overcommit while CPU check passes.

## Run It

```bash
pytest examples/real_world/pod_scheduler/ -v
praxis check examples/real_world/pod_scheduler/
praxis check examples/real_world/pod_scheduler/broken/
```
