"""Priority task queue with worker pool, retry logic, and dead letter queue.

A production-style task queue that manages task lifecycle from submission
through execution to completion, with configurable retry policies and
worker concurrency control.
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable

from praxis import runtime_guard
from examples.real_world.task_queue.spec_task_queue import TaskQueueSpec


class TaskState(Enum):
    """Task lifecycle states."""
    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    DEAD = auto()  # Max retries exceeded


@dataclass
class Task:
    """A unit of work with metadata."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    payload: Any = None
    priority: int = 0  # Lower = higher priority
    state: TaskState = TaskState.PENDING
    attempts: int = 0
    max_retries: int = 3
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    result: Any = None


class TaskQueueError(Exception):
    pass


class TaskQueue:
    """Thread-safe priority task queue with worker pool.

    Features:
    - Priority-based scheduling (lower number = higher priority)
    - Configurable worker pool size
    - Automatic retry with max attempts
    - Dead letter queue for permanently failed tasks
    - Task state tracking and lifecycle management
    - Graceful shutdown with drain
    """

    def __init__(self, max_workers: int = 4, max_queue_size: int = 10000):
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be at least 1")

        self.max_workers = max_workers
        self.max_queue_size = max_queue_size

        self._pending: queue.PriorityQueue = queue.PriorityQueue(maxsize=max_queue_size)
        self._tasks: dict[str, Task] = {}
        self._dead_letter: list[Task] = []
        self._handlers: dict[str, Callable] = {}
        self._lock = threading.Lock()
        self._workers: list[threading.Thread] = []
        self._running = False

        # Counters
        self._pending_count = 0
        self._running_count = 0
        self._completed_count = 0
        self._total_submitted = 0

    @property
    def pending_count(self) -> int:
        return self._pending_count

    @property
    def running_count(self) -> int:
        return self._running_count

    @property
    def completed_count(self) -> int:
        return self._completed_count

    @property
    def dead_letter_count(self) -> int:
        return len(self._dead_letter)

    def register_handler(self, task_name: str, handler: Callable) -> None:
        """Register a handler function for a task type."""
        self._handlers[task_name] = handler

    @runtime_guard(TaskQueueSpec, state_extractor=lambda self: {
        'pending': self._pending_count,
        'running': self._running_count,
        'completed': self._completed_count,
        'workers': self.max_workers,
        'total_submitted': self._total_submitted,
    })
    def submit(self, task: Task) -> str:
        """Submit a task to the queue. Returns the task ID."""
        with self._lock:
            if self._pending_count >= self.max_queue_size:
                raise TaskQueueError("Queue is full")
            task.state = TaskState.PENDING
            self._tasks[task.id] = task
            self._pending_count += 1
            self._total_submitted += 1

        # PriorityQueue sorts by first tuple element
        self._pending.put((task.priority, task.created_at, task.id))
        return task.id

    def get_task(self, task_id: str) -> Task | None:
        """Look up a task by ID."""
        return self._tasks.get(task_id)

    def start_workers(self) -> None:
        """Start the worker threads."""
        self._running = True
        for i in range(self.max_workers):
            t = threading.Thread(target=self._worker_loop, name=f"worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    def shutdown(self, wait: bool = True) -> None:
        """Stop all workers."""
        self._running = False
        if wait:
            for w in self._workers:
                w.join(timeout=5.0)
        self._workers.clear()

    def process_one(self, task_id: str) -> Any:
        """Synchronously process a single task. For testing."""
        task = self._tasks.get(task_id)
        if task is None:
            raise TaskQueueError(f"Unknown task: {task_id}")
        return self._execute_task(task)

    def _worker_loop(self) -> None:
        """Worker thread main loop."""
        while self._running:
            try:
                priority, created_at, task_id = self._pending.get(timeout=0.5)
            except queue.Empty:
                continue

            task = self._tasks.get(task_id)
            if task is None:
                continue

            self._execute_task(task)

    @runtime_guard(TaskQueueSpec, state_extractor=lambda self: {
        'pending': self._pending_count,
        'running': self._running_count,
        'completed': self._completed_count,
        'workers': self.max_workers,
        'total_submitted': self._total_submitted,
    })
    def _execute_task(self, task: Task) -> Any:
        """Execute a task with retry logic."""
        handler = self._handlers.get(task.name)
        if handler is None:
            task.state = TaskState.FAILED
            task.error = f"No handler registered for '{task.name}'"
            with self._lock:
                self._pending_count -= 1
            return None

        with self._lock:
            self._pending_count -= 1
            self._running_count += 1
        task.state = TaskState.RUNNING
        task.started_at = time.time()
        task.attempts += 1

        try:
            result = handler(task.payload)
            task.state = TaskState.COMPLETED
            task.result = result
            task.completed_at = time.time()
            with self._lock:
                self._running_count -= 1
                self._completed_count += 1
            return result

        except Exception as e:
            task.error = str(e)
            with self._lock:
                self._running_count -= 1

            if task.attempts < task.max_retries:
                # Retry
                task.state = TaskState.PENDING
                with self._lock:
                    self._pending_count += 1
                self._pending.put((task.priority, task.created_at, task.id))
            else:
                # Dead letter
                task.state = TaskState.DEAD
                self._dead_letter.append(task)

            return None
