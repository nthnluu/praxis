"""Pod Scheduler Spec — simplified Kubernetes-style resource management.

Proves:
- CPU allocated never exceeds node CPU capacity
- Memory allocated never exceeds node memory capacity
- Pod count never exceeds max pods per node
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class PodSchedulerSpec(Spec):
    """Simplified pod scheduler with CPU and memory bounds."""

    cpu_capacity: BoundedInt[1, 128]     # vCPUs available
    cpu_used: BoundedInt[0, 128]         # vCPUs allocated
    mem_capacity: BoundedInt[1, 512]     # GiB available
    mem_used: BoundedInt[0, 512]         # GiB allocated
    pod_count: BoundedInt[0, 110]        # Active pods
    max_pods: BoundedInt[1, 110]         # Pod limit

    @invariant
    def cpu_bounded(self):
        """CPU allocation never exceeds capacity."""
        return self.cpu_used <= self.cpu_capacity

    @invariant
    def mem_bounded(self):
        """Memory allocation never exceeds capacity."""
        return self.mem_used <= self.mem_capacity

    @invariant
    def pods_bounded(self):
        """Pod count never exceeds limit."""
        return self.pod_count <= self.max_pods

    @invariant
    def resources_non_negative(self):
        """All resource counters are non-negative."""
        return And(self.cpu_used >= 0, self.mem_used >= 0, self.pod_count >= 0)

    @transition
    def schedule_pod(self, cpu: BoundedInt[1, 16], mem: BoundedInt[1, 64]):
        """Schedule a pod onto the node."""
        require(self.cpu_used + cpu <= self.cpu_capacity)
        require(self.mem_used + mem <= self.mem_capacity)
        require(self.pod_count + 1 <= self.max_pods)
        self.cpu_used += cpu
        self.mem_used += mem
        self.pod_count += 1

    @transition
    def evict_pod(self, cpu: BoundedInt[1, 16], mem: BoundedInt[1, 64]):
        """Evict a pod from the node."""
        require(self.pod_count > 0)
        require(self.cpu_used >= cpu)
        require(self.mem_used >= mem)
        self.cpu_used -= cpu
        self.mem_used -= mem
        self.pod_count -= 1
