"""ML training job scheduler with GPU memory tracking.

Manages GPU VRAM allocation across multiple training jobs on a shared
cluster, with checkpoint scheduling and learning rate management.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from praxis import runtime_guard
from examples.real_world.ml_pipeline.spec_training import TrainingSchedulerSpec


class JobState(Enum):
    QUEUED = auto()
    RUNNING = auto()
    CHECKPOINTING = auto()
    COMPLETED = auto()
    PREEMPTED = auto()
    FAILED = auto()


@dataclass
class TrainingJob:
    """A GPU training job."""
    job_id: str
    model_name: str
    vram_required_gb: int
    batch_size: int = 32
    learning_rate: float = 0.001
    max_epochs: int = 100
    checkpoint_interval_epochs: int = 10
    state: JobState = JobState.QUEUED
    current_epoch: int = 0
    node_id: str | None = None
    started_at: float | None = None
    last_checkpoint_epoch: int = 0


@dataclass
class GPUNode:
    """A GPU node in the cluster."""
    node_id: str
    total_vram_gb: int
    allocated_vram_gb: int = 0
    active_jobs: list[str] = field(default_factory=list)

    @property
    def available_vram_gb(self) -> int:
        return self.total_vram_gb - self.allocated_vram_gb


class SchedulerError(Exception):
    pass


class InsufficientVRAMError(SchedulerError):
    pass


class TrainingScheduler:
    """GPU training job scheduler with VRAM tracking.

    Features:
    - Multi-node cluster management
    - VRAM allocation tracking per node
    - Job lifecycle management (queue → run → checkpoint → complete)
    - Preemption for priority jobs
    - Learning rate scheduling
    """

    def __init__(self):
        self._nodes: dict[str, GPUNode] = {}
        self._jobs: dict[str, TrainingJob] = {}
        self._job_queue: list[str] = []
        self._last_affected_node: GPUNode | None = None  # for runtime guard

    def add_node(self, node_id: str, vram_gb: int) -> None:
        """Register a GPU node with the scheduler."""
        if vram_gb < 1:
            raise ValueError("VRAM must be at least 1 GB")
        self._nodes[node_id] = GPUNode(node_id=node_id, total_vram_gb=vram_gb)

    def submit_job(self, job: TrainingJob) -> str:
        """Submit a training job. Returns job ID."""
        if job.vram_required_gb < 1:
            raise ValueError("VRAM requirement must be at least 1 GB")
        self._jobs[job.job_id] = job
        self._job_queue.append(job.job_id)
        return job.job_id

    @runtime_guard(TrainingSchedulerSpec, state_extractor=lambda self: {
        'vram_capacity': self._last_affected_node.total_vram_gb if self._last_affected_node else 1,
        'vram_allocated': self._last_affected_node.allocated_vram_gb if self._last_affected_node else 0,
        'active_jobs': len(self._last_affected_node.active_jobs) if self._last_affected_node else 0,
        'lr': 0.001,
        'batch_size': 32,
    })
    def schedule_job(self, job_id: str, node_id: str) -> None:
        """Schedule a queued job on a specific node."""
        job = self._get_job(job_id)
        node = self._get_node(node_id)

        if job.state != JobState.QUEUED:
            raise SchedulerError(f"Job {job_id} is not in QUEUED state")

        if node.available_vram_gb < job.vram_required_gb:
            raise InsufficientVRAMError(
                f"Node {node_id} has {node.available_vram_gb}GB free, "
                f"job needs {job.vram_required_gb}GB"
            )

        node.allocated_vram_gb += job.vram_required_gb
        node.active_jobs.append(job_id)
        job.state = JobState.RUNNING
        job.node_id = node_id
        job.started_at = time.time()
        self._last_affected_node = node

        if job_id in self._job_queue:
            self._job_queue.remove(job_id)

    @runtime_guard(TrainingSchedulerSpec, state_extractor=lambda self: {
        'vram_capacity': self._last_affected_node.total_vram_gb if self._last_affected_node else 1,
        'vram_allocated': self._last_affected_node.allocated_vram_gb if self._last_affected_node else 0,
        'active_jobs': len(self._last_affected_node.active_jobs) if self._last_affected_node else 0,
        'lr': 0.001,
        'batch_size': 32,
    })
    def preempt_job(self, job_id: str) -> None:
        """Preempt a running job, freeing its VRAM."""
        job = self._get_job(job_id)
        if job.state != JobState.RUNNING:
            raise SchedulerError(f"Job {job_id} is not running")

        node = self._nodes[job.node_id]
        node.allocated_vram_gb -= job.vram_required_gb
        node.active_jobs.remove(job_id)
        job.state = JobState.PREEMPTED
        job.node_id = None
        self._last_affected_node = node

    @runtime_guard(TrainingSchedulerSpec, state_extractor=lambda self: {
        'vram_capacity': self._last_affected_node.total_vram_gb if self._last_affected_node else 1,
        'vram_allocated': self._last_affected_node.allocated_vram_gb if self._last_affected_node else 0,
        'active_jobs': len(self._last_affected_node.active_jobs) if self._last_affected_node else 0,
        'lr': 0.001,
        'batch_size': 32,
    })
    def complete_job(self, job_id: str) -> None:
        """Mark a job as completed."""
        job = self._get_job(job_id)
        if job.state != JobState.RUNNING:
            raise SchedulerError(f"Job {job_id} is not running")

        node = self._nodes[job.node_id]
        node.allocated_vram_gb -= job.vram_required_gb
        node.active_jobs.remove(job_id)
        job.state = JobState.COMPLETED
        self._last_affected_node = node

    def scale_learning_rate(self, job_id: str, factor: float) -> None:
        """Scale a job's learning rate by a factor."""
        job = self._get_job(job_id)
        if factor <= 0:
            raise ValueError("Scale factor must be positive")
        new_lr = job.learning_rate * factor
        if new_lr <= 0 or new_lr > 10.0:
            raise ValueError(f"Resulting LR {new_lr} out of bounds")
        job.learning_rate = new_lr

    def get_cluster_utilization(self) -> dict[str, Any]:
        """Get cluster-wide utilization stats."""
        total_vram = sum(n.total_vram_gb for n in self._nodes.values())
        used_vram = sum(n.allocated_vram_gb for n in self._nodes.values())
        return {
            "total_vram_gb": total_vram,
            "used_vram_gb": used_vram,
            "utilization": used_vram / total_vram if total_vram > 0 else 0,
            "active_jobs": sum(len(n.active_jobs) for n in self._nodes.values()),
            "queued_jobs": len(self._job_queue),
        }

    def _get_job(self, job_id: str) -> TrainingJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise SchedulerError(f"Unknown job: {job_id}")
        return job

    def _get_node(self, node_id: str) -> GPUNode:
        node = self._nodes.get(node_id)
        if node is None:
            raise SchedulerError(f"Unknown node: {node_id}")
        return node
