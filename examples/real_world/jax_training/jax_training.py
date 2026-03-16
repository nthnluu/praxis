"""JAX distributed training pipeline — device allocation, sharding, and batch math.

Models multi-device JAX training without importing JAX. Accurately represents
device meshes, VRAM budgets, gradient accumulation, and sharding strategies.

The spec doesn't know about Python classes or error messages — it knows about
integers and inequalities. But the invariants it checks are the same ones that
cause 3am pages when violated.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ShardingStrategy(Enum):
    DATA_PARALLEL = auto()
    MODEL_PARALLEL = auto()
    FSDP = auto()
    PIPELINE = auto()


class JobStatus(Enum):
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class DeviceSpec:
    """A single accelerator in the mesh."""
    device_id: str
    vram_gb: int
    allocated_gb: int = 0

    @property
    def available_gb(self) -> int:
        return self.vram_gb - self.allocated_gb

    def __post_init__(self):
        if self.vram_gb < 1:
            raise ValueError(f"Device VRAM must be >= 1 GB, got {self.vram_gb}")


@dataclass
class TrainingConfig:
    """Batch and optimizer config. Key invariant: effective_batch = micro * accum."""
    micro_batch_size: int
    accumulation_steps: int
    learning_rate: float
    num_shards: int
    sharding_strategy: ShardingStrategy = ShardingStrategy.DATA_PARALLEL

    def __post_init__(self):
        if self.micro_batch_size < 1:
            raise ValueError("micro_batch_size must be >= 1")
        if self.accumulation_steps < 1:
            raise ValueError("accumulation_steps must be >= 1")
        if self.learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        if self.num_shards < 1:
            raise ValueError("num_shards must be >= 1")

    @property
    def effective_batch_size(self) -> int:
        return self.micro_batch_size * self.accumulation_steps


@dataclass
class TrainingJob:
    """A training job submitted to the cluster."""
    job_id: str
    config: TrainingConfig
    vram_required_gb: int
    status: JobStatus = JobStatus.PENDING
    assigned_devices: list[str] = field(default_factory=list)


class TrainingError(Exception):
    pass

class VRAMExhaustedError(TrainingError):
    pass

class ShardingError(TrainingError):
    pass


class DistributedTrainer:
    """Manages a JAX-style distributed training cluster.

    Handles device mesh construction, VRAM accounting, batch configuration,
    and sharding. Models the configuration layer where misconfigurations happen.
    """

    def __init__(self):
        self._devices: dict[str, DeviceSpec] = {}
        self._jobs: dict[str, TrainingJob] = {}

    def add_device(self, device_id: str, vram_gb: int) -> None:
        if device_id in self._devices:
            raise TrainingError(f"Device {device_id} already registered")
        self._devices[device_id] = DeviceSpec(device_id=device_id, vram_gb=vram_gb)

    @property
    def num_devices(self) -> int:
        return len(self._devices)

    @property
    def total_vram_gb(self) -> int:
        return sum(d.vram_gb for d in self._devices.values())

    @property
    def total_vram_allocated_gb(self) -> int:
        return sum(d.allocated_gb for d in self._devices.values())

    def submit_job(self, job: TrainingJob) -> str:
        """Submit a training job. Validates config and allocates VRAM."""
        if job.config.num_shards > self.num_devices:
            raise ShardingError(
                f"Job requires {job.config.num_shards} shards, "
                f"only {self.num_devices} devices available"
            )
        available_vram = self.total_vram_gb - self.total_vram_allocated_gb
        if job.vram_required_gb > available_vram:
            raise VRAMExhaustedError(
                f"Job needs {job.vram_required_gb} GB, only {available_vram} GB free"
            )
        # Spread VRAM allocation across shards
        per_device = job.vram_required_gb // max(job.config.num_shards, 1)
        remainder = job.vram_required_gb % max(job.config.num_shards, 1)
        available = [d for d in self._devices.values() if d.available_gb >= per_device]
        if len(available) < job.config.num_shards:
            raise VRAMExhaustedError("Not enough devices with sufficient VRAM")
        assigned = []
        for i, device in enumerate(available[:job.config.num_shards]):
            device.allocated_gb += per_device + (1 if i < remainder else 0)
            assigned.append(device.device_id)
        job.assigned_devices = assigned
        job.status = JobStatus.RUNNING
        self._jobs[job.job_id] = job
        return job.job_id

    def release_job(self, job_id: str) -> None:
        """Release VRAM when a job completes or is preempted."""
        job = self._get_job(job_id)
        if job.status != JobStatus.RUNNING:
            raise TrainingError(f"Job {job_id} is not running")
        per_device = job.vram_required_gb // max(len(job.assigned_devices), 1)
        remainder = job.vram_required_gb % max(len(job.assigned_devices), 1)
        for i, dev_id in enumerate(job.assigned_devices):
            freed = per_device + (1 if i < remainder else 0)
            self._devices[dev_id].allocated_gb = max(0, self._devices[dev_id].allocated_gb - freed)
        job.status = JobStatus.COMPLETED
        job.assigned_devices = []

    def scale_batch(self, job_id: str, new_micro: int, new_accum: int) -> None:
        """Change batch dimensions, keeping effective batch size constant."""
        job = self._get_job(job_id)
        if new_micro < 1 or new_accum < 1:
            raise ValueError("Batch dimensions must be >= 1")
        old_effective = job.config.effective_batch_size
        new_effective = new_micro * new_accum
        if new_effective != old_effective:
            raise TrainingError(
                f"Batch mismatch: {new_micro} * {new_accum} = {new_effective}, "
                f"expected {old_effective}"
            )
        job.config.micro_batch_size = new_micro
        job.config.accumulation_steps = new_accum

    def update_lr(self, job_id: str, factor: float) -> None:
        """Scale learning rate. Guards against zero/negative LR."""
        job = self._get_job(job_id)
        if factor <= 0:
            raise ValueError("LR scale factor must be positive")
        new_lr = job.config.learning_rate * factor
        if new_lr <= 0:
            raise TrainingError("Learning rate would become non-positive")
        if new_lr > 10.0:
            raise TrainingError(f"Learning rate {new_lr} exceeds maximum (10.0)")
        job.config.learning_rate = new_lr

    def reshard(self, job_id: str, new_shards: int,
                strategy: ShardingStrategy | None = None) -> None:
        """Change the parallelism strategy mid-training."""
        job = self._get_job(job_id)
        if new_shards < 1:
            raise ValueError("num_shards must be >= 1")
        if new_shards > self.num_devices:
            raise ShardingError(
                f"Cannot shard across {new_shards} devices, "
                f"only {self.num_devices} available"
            )
        job.config.num_shards = new_shards
        if strategy is not None:
            job.config.sharding_strategy = strategy

    def get_cluster_status(self) -> dict[str, Any]:
        total, used = self.total_vram_gb, self.total_vram_allocated_gb
        return {
            "num_devices": self.num_devices,
            "total_vram_gb": total,
            "allocated_vram_gb": used,
            "utilization": used / total if total > 0 else 0.0,
            "running_jobs": sum(1 for j in self._jobs.values() if j.status == JobStatus.RUNNING),
        }

    def _get_job(self, job_id: str) -> TrainingJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise TrainingError(f"Unknown job: {job_id}")
        return job
