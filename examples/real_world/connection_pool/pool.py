"""Thread-safe database connection pool.

Manages a bounded set of reusable connections with health checks,
idle timeout eviction, and max lifetime enforcement.

Usage:
    pool = ConnectionPool(dsn="postgresql://localhost/mydb", max_size=10)
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    pool.close()
"""

from __future__ import annotations

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from praxis import runtime_guard

try:
    from .spec_pool import ConnectionPoolSpec
except ImportError:
    import importlib.util, pathlib
    _spec = importlib.util.spec_from_file_location(
        "spec_pool", pathlib.Path(__file__).parent / "spec_pool.py")
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    ConnectionPoolSpec = _mod.ConnectionPoolSpec


class PoolExhaustedError(Exception):
    """No connection available and the pool is at max capacity."""


@dataclass
class PooledConnection:
    """Connection wrapper with pool metadata."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    dsn: str = ""
    created_at: float = field(default_factory=time.time)
    last_used_at: float = field(default_factory=time.time)
    last_checked_at: float = 0.0
    use_count: int = 0
    _closed: bool = False

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> list[Any]:
        """Execute a query (stub for demonstration)."""
        if self._closed:
            raise RuntimeError(f"Connection {self.id} is closed")
        self.use_count += 1
        self.last_used_at = time.time()
        return []

    def ping(self) -> bool:
        """Health check — returns False if the connection is dead."""
        if self._closed:
            return False
        self.last_checked_at = time.time()
        return True

    def close(self) -> None:
        self._closed = True

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def age(self) -> float:
        return time.time() - self.created_at

    @property
    def idle_time(self) -> float:
        return time.time() - self.last_used_at


class ConnectionPool:
    """Thread-safe connection pool with health checks and eviction.

    Args:
        dsn: Database connection string.
        max_size: Maximum connections (active + idle).
        idle_timeout: Seconds before an idle connection is evictable.
        max_lifetime: Max seconds a connection may live.
        health_check_interval: Seconds between checkout health checks (0 = always).
        connect_factory: Optional callable to create a PooledConnection.
    """

    def __init__(
        self,
        dsn: str = "sqlite:///:memory:",
        max_size: int = 10,
        min_idle: int = 1,
        idle_timeout: float = 300.0,
        max_lifetime: float = 3600.0,
        health_check_interval: float = 30.0,
        connect_factory: Optional[Callable[[str], PooledConnection]] = None,
    ) -> None:
        if max_size < 1:
            raise ValueError("max_size must be at least 1")

        self._dsn = dsn
        self._max_size = max_size
        self._min_idle = min(min_idle, max_size)
        self._idle_timeout = idle_timeout
        self._max_lifetime = max_lifetime
        self._health_check_interval = health_check_interval
        self._factory = connect_factory or (lambda d: PooledConnection(dsn=d))
        self._idle: queue.Queue[PooledConnection] = queue.Queue(maxsize=max_size)
        self._active: set[str] = set()
        self._lock = threading.Lock()
        self._closed = False

    def _pool_state(self) -> dict[str, int]:
        """Extract spec state from the pool for runtime invariant checking."""
        active = len(self._active)
        idle = self._idle.qsize()
        return {
            'active': active,
            'idle': idle,
            'max_size': self._max_size,
            'total_created': active + idle,
        }

    def connection(self) -> _ConnectionContext:
        """Context manager: checks out on enter, checks in on exit."""
        return _ConnectionContext(self)

    @runtime_guard(ConnectionPoolSpec, state_extractor=lambda self: self._pool_state())
    def checkout(self) -> PooledConnection:
        """Check out a connection, creating one if needed."""
        if self._closed:
            raise RuntimeError("Pool is closed")

        conn = self._try_get_idle() or self.create_connection()
        if conn is None:
            raise PoolExhaustedError(
                f"Pool exhausted: {len(self._active)} active, max={self._max_size}"
            )

        # Configurable health check
        needs_check = (self._health_check_interval <= 0 or
                       (time.time() - conn.last_checked_at) >= self._health_check_interval)
        if needs_check and not conn.ping():
            conn.close()
            return self.checkout()

        # Max lifetime enforcement
        if conn.age >= self._max_lifetime:
            conn.close()
            return self.checkout()

        with self._lock:
            self._active.add(conn.id)
        conn.last_used_at = time.time()
        return conn

    @runtime_guard(ConnectionPoolSpec, state_extractor=lambda self: self._pool_state())
    def checkin(self, conn: PooledConnection) -> None:
        """Return a connection. Destroys it if expired or closed."""
        with self._lock:
            self._active.discard(conn.id)

        if conn.is_closed or conn.age >= self._max_lifetime:
            conn.close()
            return
        try:
            self._idle.put_nowait(conn)
        except queue.Full:
            conn.close()

    @runtime_guard(ConnectionPoolSpec, state_extractor=lambda self: self._pool_state())
    def create_connection(self) -> Optional[PooledConnection]:
        """Create a new connection if the pool has capacity."""
        with self._lock:
            if len(self._active) + self._idle.qsize() + 1 > self._max_size:
                return None
            return self._factory(self._dsn)

    @runtime_guard(ConnectionPoolSpec, state_extractor=lambda self: self._pool_state())
    def destroy_idle(self) -> int:
        """Evict idle connections past their timeout. Respects min_idle."""
        destroyed = 0
        survivors: list[PooledConnection] = []

        while True:
            try:
                conn = self._idle.get_nowait()
            except queue.Empty:
                break
            if conn.idle_time >= self._idle_timeout and len(survivors) >= self._min_idle:
                conn.close()
                destroyed += 1
            else:
                survivors.append(conn)

        for conn in survivors:
            try:
                self._idle.put_nowait(conn)
            except queue.Full:
                conn.close()
                destroyed += 1
        return destroyed

    def close(self) -> None:
        """Close the pool and all idle connections."""
        self._closed = True
        while True:
            try:
                self._idle.get_nowait().close()
            except queue.Empty:
                break

    def _try_get_idle(self) -> Optional[PooledConnection]:
        try:
            return self._idle.get_nowait()
        except queue.Empty:
            return None

    def __enter__(self) -> ConnectionPool:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


class _ConnectionContext:
    """Context manager: __enter__ checks out, __exit__ checks in."""

    def __init__(self, pool: ConnectionPool) -> None:
        self._pool = pool
        self._conn: Optional[PooledConnection] = None

    def __enter__(self) -> PooledConnection:
        self._conn = self._pool.checkout()
        return self._conn

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._conn is not None:
            self._pool.checkin(self._conn)
            self._conn = None
