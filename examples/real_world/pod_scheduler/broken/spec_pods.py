"""Broken pod scheduler spec — schedule_pod checks CPU but not memory.

Bug: schedule_pod only guards cpu_used + cpu <= cpu_capacity but
doesn't guard mem_used + mem <= mem_capacity. This violates
the mem_bounded invariant.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenPodSchedulerSpec(Spec):
    cpu_capacity: BoundedInt[1, 128]
    cpu_used: BoundedInt[0, 128]
    mem_capacity: BoundedInt[1, 512]
    mem_used: BoundedInt[0, 512]
    pod_count: BoundedInt[0, 110]
    max_pods: BoundedInt[1, 110]

    @invariant
    def cpu_bounded(self):
        return self.cpu_used <= self.cpu_capacity

    @invariant
    def mem_bounded(self):
        return self.mem_used <= self.mem_capacity

    @invariant
    def pods_bounded(self):
        return self.pod_count <= self.max_pods

    @transition
    def schedule_pod(self, cpu: BoundedInt[1, 16], mem: BoundedInt[1, 64]):
        """BUG: Checks CPU but NOT memory."""
        require(self.cpu_used + cpu <= self.cpu_capacity)
        # Missing: require(self.mem_used + mem <= self.mem_capacity)
        require(self.pod_count + 1 <= self.max_pods)
        self.cpu_used += cpu
        self.mem_used += mem
        self.pod_count += 1

    @transition
    def evict_pod(self, cpu: BoundedInt[1, 16], mem: BoundedInt[1, 64]):
        require(self.pod_count > 0)
        require(self.cpu_used >= cpu)
        require(self.mem_used >= mem)
        self.cpu_used -= cpu
        self.mem_used -= mem
        self.pod_count -= 1
