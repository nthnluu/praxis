# Data Pipeline Backpressure

## The Problem

Every non-trivial data pipeline has to answer the same question: what happens
when producers are faster than consumers? The naive answer -- buffer everything
in an unbounded queue -- works until it doesn't. In production, "doesn't work"
usually means the queue grows until the process exhausts available memory and
the OS kills it. This is one of the most common failure modes in
stream-processing systems, ETL jobs, and microservice message buses.

The standard solution is **backpressure**: the queue has a hard capacity limit,
and producers that try to exceed it are forced to slow down by blocking until
space is available. This couples the producer rate to the consumer rate and
prevents unbounded memory growth. Systems like Kafka, TCP flow control, and
reactive streams all implement variants of this idea.

Getting backpressure right is subtle. The capacity check must happen atomically
with the enqueue operation. If a producer checks "is there space?" and then
enqueues in a separate step, a race condition can push the queue past its
limit. With batch operations and dynamic resizing, the surface area for bugs
grows. A formal specification lets us prove the invariants hold across all
possible interleavings, not just the ones our tests happen to exercise.

## The Implementation

`pipeline.py` implements `BoundedQueue[T]`, a generic async bounded queue built
on `asyncio`. The design uses two condition variables -- `_not_full` and
`_not_empty` -- to implement blocking backpressure without busy-waiting:

- **`produce(item)`** acquires the `_not_full` condition, waits in a loop while
  the buffer is at capacity, then appends the item and signals `_not_empty`.
- **`consume()`** acquires the `_not_empty` condition, waits in a loop while
  the buffer is empty, then pops the oldest item and signals `_not_full`.
- **`produce_batch` / `consume_batch`** delegate to the single-item methods,
  applying backpressure per item.
- **`resize(new_capacity)`** updates the capacity under the `_not_full` lock
  and wakes blocked producers if the new limit is higher.
- **`drain()`** closes the queue, returns remaining items, and wakes all
  waiters so they see the closed state.

A `PipelineStats` dataclass tracks `messages_produced`, `messages_consumed`,
`messages_dropped`, and `peak_queue_size` for observability.

## The Spec

`spec_pipeline.py` models the queue as four integers:

| Variable      | Meaning                        |
|---------------|--------------------------------|
| `queue_size`  | Current number of items        |
| `capacity`    | Maximum allowed items          |
| `produced`    | Total items ever enqueued      |
| `consumed`    | Total items ever dequeued      |

Four invariants constrain the system:

1. **`bounded`** -- `queue_size <= capacity`. The fundamental safety property:
   the queue never exceeds its limit.
2. **`non_negative`** -- `queue_size >= 0`. You cannot have a negative number
   of items.
3. **`no_phantom_reads`** -- `consumed <= produced`. A consumer cannot dequeue
   an item that was never enqueued.
4. **`queue_consistent`** -- `queue_size == produced - consumed`. The current
   size is always exactly the difference between total enqueues and total
   dequeues. This catches off-by-one errors and double-count bugs.

Two transitions model the operations:

- **`produce(count)`** -- requires `queue_size + count <= capacity` (the
  backpressure guard), then increments `queue_size` and `produced`.
- **`consume(count)`** -- requires `queue_size >= count` (can't consume more
  than exists), then decrements `queue_size` and increments `consumed`.

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/data_pipeline/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    queue,
    BoundedQueueSpec,
    state_extractor=lambda self: {
        'queue_size': len(self._buffer),
        'capacity': self._capacity,
        'produced': self._stats.messages_produced,
        'consumed': self._stats.messages_consumed,
    },
    operations=[
        lambda q: q._do_enqueue(some_item),
        lambda q: q._do_dequeue(),
    ],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    BoundedQueue,
    BoundedQueueSpec,
    state_extractor=lambda self: {
        'queue_size': len(self._buffer), 'capacity': self._capacity,
        'produced': self._stats.messages_produced,
        'consumed': self._stats.messages_consumed,
    },
    methods=["_do_enqueue", "_do_dequeue"],
    mode="log",
)
```

### 4. Per-method decorators (legacy, still supported)

The sync helpers `_do_enqueue()` and `_do_dequeue()` are currently decorated with `@runtime_guard`:

```python
@runtime_guard(BoundedQueueSpec, state_extractor=lambda self: {
    'queue_size': len(self._buffer),
    'capacity': self._capacity,
    'produced': self._stats.messages_produced,
    'consumed': self._stats.messages_consumed,
})
def _do_enqueue(self, item: T) -> None: ...
```

After every enqueue or dequeue, the guard verifies that the queue never exceeds capacity, never goes negative, no phantom reads occur, and `queue_size == produced - consumed`. An `AssertionError` fires immediately if the buffer or counters drift out of spec.

## What Praxis Proves

1. No sequence of produce/consume operations can ever push the queue past its
   capacity, no matter how many producers or what order they run in.
2. The queue size can never go negative, even with concurrent consumers racing
   to drain the last items.
3. Every consumed message was previously produced -- there are no phantom reads
   or double-deliveries at the specification level.
4. The queue size is always exactly `produced - consumed`, meaning the counters
   stay consistent across all reachable states.
5. The backpressure guard (`queue_size + count <= capacity`) is necessary and
   sufficient: removing it breaks the `bounded` invariant (see below), and
   keeping it is enough to guarantee all four invariants simultaneously.

## The Bug Praxis Catches

The `broken/spec_pipeline.py` file contains a version of the spec where the
`produce` transition is missing the capacity check:

```python
@transition
def produce(self, count: BoundedInt[1, 100]):
    """BUG: No backpressure -- missing capacity check."""
    # Missing: require(self.queue_size + count <= self.capacity)
    self.queue_size += count
    self.produced += count
```

Without the guard `require(self.queue_size + count <= self.capacity)`, a single
`produce(count=100)` call on a queue with `capacity=1` pushes `queue_size` to
100, violating the `bounded` invariant. Praxis finds this counterexample
automatically: it reports the exact initial state and transition sequence that
breaks the invariant.

This mirrors a real class of bugs where a developer implements the queue
operations but forgets (or incorrectly implements) the "wait until there's
space" logic. The system appears to work in testing -- where producers are slow
and the queue never fills -- but fails under production load when the buffer
overflows.

## Run

Check the correct spec (should pass):

```bash
praxis check examples/real_world/data_pipeline/spec_pipeline.py
```

Check the broken spec (should find a counterexample):

```bash
praxis check examples/real_world/data_pipeline/broken/spec_pipeline.py
```

Run any associated tests:

```bash
pytest examples/real_world/data_pipeline/ -v
```
