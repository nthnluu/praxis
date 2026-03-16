# Connection Pool

## The Problem

Database connection pools are the silent backbone of every backend service. They manage a finite, expensive resource -- open connections to a database server -- and share them across many concurrent requests. When they work, nobody notices. When they break, the consequences cascade: connections leak until the database hits its max, new requests stall, and the service falls over.

The most common pool bug is overflow: the pool creates more connections than its configured maximum. This happens when the capacity check is missing, racy, or performed at the wrong moment. Under light load, the bug is invisible because the pool rarely reaches its limit. Under production traffic, the pool silently opens 200 connections to a PostgreSQL server configured for 100, and the database starts rejecting connections from every service on the cluster.

The second class of bugs involves lifetime management. Connections that aren't health-checked go stale and hand back broken sockets. Connections that aren't evicted after an idle timeout pile up and consume memory. Connections that live past their max lifetime may hold server-side state (temp tables, advisory locks) that should have been cleaned up. These bugs are timing-dependent and almost impossible to reproduce in a test suite that runs in milliseconds.

## The Implementation

`pool.py` -- A thread-safe `ConnectionPool` using Python's `threading.Lock` and `queue.Queue`:

- **`PooledConnection`**: A dataclass wrapping a connection with metadata -- creation time, last-used time, use count, and health-check timestamp
- **`ConnectionPool`**: The pool itself, with configurable `max_size`, `idle_timeout`, `max_lifetime`, and `health_check_interval`
- **`_ConnectionContext`**: A context manager (`__enter__`/`__exit__`) that guarantees connections are always returned to the pool, even if an exception is thrown

Key methods:
```python
class ConnectionPool:
    def checkout(self) -> PooledConnection     # Get a connection (creates if needed)
    def checkin(self, conn) -> None             # Return a connection
    def create_connection(self) -> Optional[PooledConnection]  # New conn if capacity allows
    def destroy_idle(self) -> int               # Evict stale idle connections
    def connection(self) -> _ConnectionContext  # Context manager for safe usage
```

The pool lazily creates connections on `checkout` when the idle queue is empty and capacity remains. On `checkin`, connections that have exceeded `max_lifetime` are destroyed rather than returned. The `destroy_idle` method walks the idle queue and evicts connections past their `idle_timeout`, while respecting a `min_idle` floor.

## The Spec

`spec_pool.py` models the pool as four integer counters:

- **`max_size`**: The configured ceiling (1--100)
- **`active`**: Connections currently checked out
- **`idle`**: Connections sitting in the idle queue
- **`total_created`**: Sum of all connections ever created (must equal `active + idle`)

Three invariants constrain every reachable state:

1. **`active_bounded`**: `active + idle <= max_size` -- the pool never exceeds its limit
2. **`non_negative`**: `active >= 0` and `idle >= 0` -- counters cannot go negative
3. **`total_consistent`**: `total_created == active + idle` -- creation and destruction stay balanced

Four transitions model the operations:

- **`checkout`**: Requires `idle > 0`. Moves one connection from idle to active.
- **`checkin`**: Requires `active > 0`. Moves one connection from active to idle.
- **`create_connection`**: Requires `active + idle + 1 <= max_size`. Increments idle and total_created.
- **`destroy_idle`**: Requires `idle > 0`. Decrements idle and total_created.

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/connection_pool/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    pool,
    ConnectionPoolSpec,
    state_extractor=lambda self: self._pool_state(),
    operations=[
        lambda p: p.checkout(),
        lambda p: p.checkin(p.checkout()),
        lambda p: p.create_connection(),
        lambda p: p.destroy_idle(),
    ],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    ConnectionPool,
    ConnectionPoolSpec,
    state_extractor=lambda self: self._pool_state(),
    methods=["checkout", "checkin", "create_connection", "destroy_idle"],
    mode="log",
)
```

### 4. Per-method decorators (legacy, still supported)

The implementation currently uses `@runtime_guard` on `checkout`, `checkin`, `create_connection`, and `destroy_idle`:

```python
@runtime_guard(ConnectionPoolSpec, state_extractor=lambda self: self._pool_state())
def checkout(self) -> PooledConnection: ...
```

The `_pool_state()` helper maps the implementation's internals to the spec's abstract counters:

| Spec variable    | Implementation source                  |
|-------------------|----------------------------------------|
| `active`         | `len(self._active)` (set of connection IDs) |
| `idle`           | `self._idle.qsize()` (Queue size)       |
| `max_size`       | `self._max_size`                        |
| `total_created`  | `active + idle` (derived)               |

If any operation leaves `active + idle > max_size`, the `active_bounded` invariant fires an `AssertionError` before the overflow can cause downstream database connection errors.

## What Praxis Proves

For every possible combination of `max_size`, `active`, `idle`, and `total_created`:

1. The pool never holds more connections (active + idle) than `max_size`, no matter what sequence of checkouts, checkins, creates, and destroys occurs
2. Active and idle counts never go negative, even under arbitrary interleaving
3. The total-created counter stays perfectly synchronized with active + idle -- no connections are "lost" or double-counted
4. Every transition preserves all three invariants simultaneously -- there is no sequence of operations that can violate them
5. The `create_connection` guard is necessary and sufficient to prevent overflow

## The Bug Praxis Catches

In `broken/spec_pool.py`, the `create_connection` transition is missing its capacity guard:

```python
@transition
def create_connection(self, dummy: BoundedInt[0, 0]):
    """BUG: Create a new connection WITHOUT checking capacity."""
    # Missing: require(self.active + self.idle + 1 <= self.max_size)
    require(self.total_created + 1 <= 100)
    self.idle += 1
    self.total_created += 1
```

Praxis finds this immediately:

```
INVARIANT VIOLATED: active_bounded

  Counterexample:
    max_size = 1
    active = 0
    idle = 1
    total_created = 1

  After transition `create_connection`:
    max_size' = 1
    active' = 0
    idle' = 2
    total_created' = 2
```

Translation: a pool configured with `max_size=1` already has one idle connection. Without the capacity guard, `create_connection` happily adds a second, pushing `idle` to 2 -- which violates `active + idle <= max_size`.

This bug is hard to catch with traditional testing because it requires a specific race condition: two threads both see the pool as "not full" and both proceed to create a connection simultaneously. In a single-threaded test, the pool dutifully checks capacity and the overflow never occurs. In production under concurrent load, the missing guard lets the pool silently exceed its limit, and the first symptom is a cryptic "too many connections" error from the database -- minutes or hours after the actual overflow happened.

Praxis doesn't rely on timing or concurrency. It exhaustively checks that the capacity guard is the only thing preventing overflow, and proves that without it, a single `create_connection` call on an already-full pool breaks the invariant.

## Run It

```bash
# Verify the correct implementation
pytest examples/real_world/connection_pool/ -v
praxis check examples/real_world/connection_pool/

# See Praxis catch the bug
praxis check examples/real_world/connection_pool/broken/
```
