"""Async bounded queue with backpressure for data pipelines.

A producer-consumer queue that enforces a hard capacity limit.  When the queue
is full, producers block until space is available rather than dropping messages
or growing without bound.  Prevents OOM kills in stream-processing systems.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from praxis import runtime_guard
from examples.real_world.data_pipeline.spec_pipeline import BoundedQueueSpec

T = TypeVar("T")


@dataclass
class PipelineStats:
    """Runtime statistics for a bounded queue."""

    messages_produced: int = 0
    messages_consumed: int = 0
    messages_dropped: int = 0
    peak_queue_size: int = 0
    created_at: float = field(default_factory=time.monotonic)

    @property
    def total_throughput(self) -> int:
        """Total messages that have passed through the queue."""
        return self.messages_consumed

    @property
    def uptime(self) -> float:
        """Seconds since the queue was created."""
        return time.monotonic() - self.created_at

    @property
    def in_flight(self) -> int:
        """Messages produced but not yet consumed."""
        return self.messages_produced - self.messages_consumed


class QueueFullError(Exception):
    """Raised when a non-blocking produce is attempted on a full queue."""


class QueueEmptyError(Exception):
    """Raised when a non-blocking consume is attempted on an empty queue."""


class BoundedQueue(Generic[T]):
    """Async bounded queue with backpressure.

    When the queue reaches capacity, ``produce()`` blocks until a consumer
    frees space.  Uses two ``asyncio.Condition`` variables for efficient
    waiting without busy-loops.

    Usage::

        async with BoundedQueue(capacity=100) as q:
            await q.produce("msg-1")
            item = await q.consume()
    """

    def __init__(self, capacity: int = 1000) -> None:
        if capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {capacity}")
        self._capacity = capacity
        self._buffer: deque[T] = deque()
        self._stats = PipelineStats()
        self._closed = False
        self._not_full = asyncio.Condition()
        self._not_empty = asyncio.Condition()

    @property
    def capacity(self) -> int:
        """Current maximum capacity."""
        return self._capacity

    @property
    def size(self) -> int:
        """Number of items currently in the queue."""
        return len(self._buffer)

    @property
    def is_full(self) -> bool:
        """True if the queue is at capacity."""
        return len(self._buffer) >= self._capacity

    @property
    def is_empty(self) -> bool:
        """True if the queue has no items."""
        return len(self._buffer) == 0

    @property
    def stats(self) -> PipelineStats:
        """Runtime statistics snapshot."""
        return self._stats

    # -- Guarded sync helpers (runtime_guard works on sync functions) --

    @runtime_guard(BoundedQueueSpec, state_extractor=lambda self: {
        'queue_size': len(self._buffer),
        'capacity': self._capacity,
        'produced': self._stats.messages_produced,
        'consumed': self._stats.messages_consumed,
    })
    def _do_enqueue(self, item: T) -> None:
        """Synchronous enqueue: append item and update stats."""
        self._buffer.append(item)
        self._stats.messages_produced += 1
        if len(self._buffer) > self._stats.peak_queue_size:
            self._stats.peak_queue_size = len(self._buffer)

    @runtime_guard(BoundedQueueSpec, state_extractor=lambda self: {
        'queue_size': len(self._buffer),
        'capacity': self._capacity,
        'produced': self._stats.messages_produced,
        'consumed': self._stats.messages_consumed,
    })
    def _do_dequeue(self) -> T:
        """Synchronous dequeue: pop item and update stats."""
        item = self._buffer.popleft()
        self._stats.messages_consumed += 1
        return item

    # -- Core operations --

    async def produce(self, item: T) -> None:
        """Add an item, blocking until space is available (backpressure)."""
        async with self._not_full:
            if self._closed:
                raise RuntimeError("Cannot produce to a closed queue")
            while len(self._buffer) >= self._capacity:
                await self._not_full.wait()
                if self._closed:
                    raise RuntimeError("Cannot produce to a closed queue")
            self._do_enqueue(item)
        async with self._not_empty:
            self._not_empty.notify()

    async def consume(self) -> T:
        """Remove and return the oldest item, blocking until one is available."""
        async with self._not_empty:
            while len(self._buffer) == 0:
                if self._closed:
                    raise RuntimeError("Queue is closed and empty")
                await self._not_empty.wait()
            item = self._do_dequeue()
        async with self._not_full:
            self._not_full.notify()
        return item

    # -- Batch operations --

    async def produce_batch(self, items: list[T]) -> int:
        """Produce multiple items, applying backpressure per-item.

        Returns the number of items successfully produced.
        """
        count = 0
        for item in items:
            await self.produce(item)
            count += 1
        return count

    async def consume_batch(self, max_items: int) -> list[T]:
        """Consume up to *max_items*.  Blocks for the first, then drains
        up to *max_items* total without waiting further.
        """
        if max_items < 1:
            raise ValueError("max_items must be >= 1")
        result: list[T] = [await self.consume()]
        while len(result) < max_items and len(self._buffer) > 0:
            result.append(await self.consume())
        return result

    # -- Lifecycle --

    async def drain(self) -> list[T]:
        """Close the queue and return all remaining items.

        After draining, no new items can be produced.  Blocked waiters
        receive a ``RuntimeError``.
        """
        self._closed = True
        remaining: list[T] = list(self._buffer)
        self._stats.messages_dropped += len(remaining)
        self._buffer.clear()
        async with self._not_full:
            self._not_full.notify_all()
        async with self._not_empty:
            self._not_empty.notify_all()
        return remaining

    async def resize(self, new_capacity: int) -> None:
        """Change capacity at runtime.

        If larger, blocked producers may be woken.  If smaller, existing
        items are retained but future produces block until size drops.
        """
        if new_capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {new_capacity}")
        async with self._not_full:
            self._capacity = new_capacity
            if len(self._buffer) < self._capacity:
                self._not_full.notify_all()

    # -- Context manager --

    async def __aenter__(self) -> BoundedQueue[T]:
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.drain()
