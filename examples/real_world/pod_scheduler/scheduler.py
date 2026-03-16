"""Kubernetes-style pod scheduler with resource bin-packing.

Assigns pods to nodes based on CPU and memory requests, with
capacity enforcement and eviction support.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from praxis import runtime_guard
from examples.real_world.pod_scheduler.spec_pods import PodSchedulerSpec


@dataclass
class Pod:
    """A pod to be scheduled."""
    name: str
    cpu_request: int      # millicores
    memory_request_mb: int
    priority: int = 0     # Higher = more important
    evictable: bool = True
    node: str | None = None


@dataclass
class Node:
    """A cluster node with resource capacity."""
    name: str
    cpu_capacity: int          # millicores
    memory_capacity_mb: int
    max_pods: int = 110
    cpu_allocated: int = 0
    memory_allocated_mb: int = 0
    pods: list[str] = field(default_factory=list)
    cordoned: bool = False

    @property
    def cpu_available(self) -> int:
        return self.cpu_capacity - self.cpu_allocated

    @property
    def memory_available_mb(self) -> int:
        return self.memory_capacity_mb - self.memory_allocated_mb

    @property
    def pod_count(self) -> int:
        return len(self.pods)


class SchedulerError(Exception):
    pass


class InsufficientResourcesError(SchedulerError):
    pass


class PodScheduler:
    """Pod scheduler with resource tracking and bin-packing.

    Features:
    - CPU and memory capacity enforcement per node
    - Pod count limit per node
    - Node cordoning (no new pods)
    - Eviction by priority
    - Resource scoring for bin-packing
    """

    def __init__(self):
        self._nodes: dict[str, Node] = {}
        self._pods: dict[str, Pod] = {}
        self._last_affected_node: Node | None = None  # for runtime guard

    def add_node(self, name: str, cpu: int, memory_mb: int, max_pods: int = 110) -> None:
        """Register a node."""
        if cpu < 1 or memory_mb < 1:
            raise ValueError("CPU and memory must be positive")
        self._nodes[name] = Node(
            name=name, cpu_capacity=cpu,
            memory_capacity_mb=memory_mb, max_pods=max_pods,
        )

    @runtime_guard(PodSchedulerSpec, state_extractor=lambda self: {
        'cpu_used': self._last_affected_node.cpu_allocated if self._last_affected_node else 0,
        'cpu_capacity': self._last_affected_node.cpu_capacity if self._last_affected_node else 1,
        'mem_used': self._last_affected_node.memory_allocated_mb if self._last_affected_node else 0,
        'mem_capacity': self._last_affected_node.memory_capacity_mb if self._last_affected_node else 1,
        'pod_count': self._last_affected_node.pod_count if self._last_affected_node else 0,
        'max_pods': self._last_affected_node.max_pods if self._last_affected_node else 1,
    })
    def schedule_pod(self, pod: Pod) -> str:
        """Schedule a pod on the best available node. Returns node name."""
        candidates = self._score_nodes(pod)
        if not candidates:
            raise InsufficientResourcesError(
                f"No node can fit pod '{pod.name}' "
                f"(cpu={pod.cpu_request}, mem={pod.memory_request_mb}MB)"
            )

        # Pick the node with highest score (most resources consumed = tightest fit)
        best_node_name = max(candidates, key=candidates.get)
        node = self._nodes[best_node_name]

        node.cpu_allocated += pod.cpu_request
        node.memory_allocated_mb += pod.memory_request_mb
        node.pods.append(pod.name)
        pod.node = node.name
        self._pods[pod.name] = pod
        self._last_affected_node = node
        return node.name

    @runtime_guard(PodSchedulerSpec, state_extractor=lambda self: {
        'cpu_used': self._last_affected_node.cpu_allocated if self._last_affected_node else 0,
        'cpu_capacity': self._last_affected_node.cpu_capacity if self._last_affected_node else 1,
        'mem_used': self._last_affected_node.memory_allocated_mb if self._last_affected_node else 0,
        'mem_capacity': self._last_affected_node.memory_capacity_mb if self._last_affected_node else 1,
        'pod_count': self._last_affected_node.pod_count if self._last_affected_node else 0,
        'max_pods': self._last_affected_node.max_pods if self._last_affected_node else 1,
    })
    def evict_pod(self, pod_name: str) -> None:
        """Evict a pod from its node."""
        pod = self._pods.get(pod_name)
        if pod is None:
            raise SchedulerError(f"Unknown pod: {pod_name}")
        if pod.node is None:
            raise SchedulerError(f"Pod '{pod_name}' is not scheduled")
        if not pod.evictable:
            raise SchedulerError(f"Pod '{pod_name}' is not evictable")

        node = self._nodes[pod.node]
        node.cpu_allocated -= pod.cpu_request
        node.memory_allocated_mb -= pod.memory_request_mb
        node.pods.remove(pod_name)
        pod.node = None
        self._last_affected_node = node

    def cordon_node(self, name: str) -> None:
        """Mark a node as unschedulable."""
        node = self._nodes.get(name)
        if node is None:
            raise SchedulerError(f"Unknown node: {name}")
        node.cordoned = True

    def uncordon_node(self, name: str) -> None:
        """Mark a node as schedulable again."""
        node = self._nodes.get(name)
        if node is None:
            raise SchedulerError(f"Unknown node: {name}")
        node.cordoned = False

    def drain_node(self, name: str) -> list[str]:
        """Evict all evictable pods from a node. Returns evicted pod names."""
        node = self._nodes.get(name)
        if node is None:
            raise SchedulerError(f"Unknown node: {name}")

        self.cordon_node(name)
        evicted = []
        for pod_name in list(node.pods):
            pod = self._pods[pod_name]
            if pod.evictable:
                self.evict_pod(pod_name)
                evicted.append(pod_name)
        return evicted

    def _score_nodes(self, pod: Pod) -> dict[str, float]:
        """Score nodes for scheduling. Higher = better fit."""
        scores = {}
        for name, node in self._nodes.items():
            if node.cordoned:
                continue
            if node.cpu_available < pod.cpu_request:
                continue
            if node.memory_available_mb < pod.memory_request_mb:
                continue
            if node.pod_count >= node.max_pods:
                continue

            # Score: prefer nodes with less remaining capacity (bin-packing)
            cpu_usage = node.cpu_allocated / node.cpu_capacity
            mem_usage = node.memory_allocated_mb / node.memory_capacity_mb
            scores[name] = (cpu_usage + mem_usage) / 2

        return scores
