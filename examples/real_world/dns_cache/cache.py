"""DNS cache with TTL-based expiration and LRU eviction.

A production-style DNS cache that stores A/AAAA/CNAME records with
per-entry TTL, LRU eviction when capacity is reached, and hit/miss
statistics for monitoring.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from praxis import runtime_guard

try:
    from .spec_dns_cache import DNSCacheSpec
except ImportError:
    import importlib.util, pathlib
    _spec = importlib.util.spec_from_file_location(
        "spec_dns_cache", pathlib.Path(__file__).parent / "spec_dns_cache.py")
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    DNSCacheSpec = _mod.DNSCacheSpec


class RecordType(Enum):
    """DNS record types."""
    A = "A"
    AAAA = "AAAA"
    CNAME = "CNAME"
    MX = "MX"
    TXT = "TXT"


@dataclass
class DNSRecord:
    """A cached DNS record."""
    name: str
    record_type: RecordType
    value: str
    ttl: float
    inserted_at: float = field(default_factory=time.time)

    @property
    def expires_at(self) -> float:
        return self.inserted_at + self.ttl

    @property
    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def remaining_ttl(self) -> float:
        return max(0.0, self.expires_at - time.time())


@dataclass
class CacheStats:
    """Cache performance statistics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    insertions: int = 0

    @property
    def total_lookups(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.total_lookups == 0:
            return 0.0
        return self.hits / self.total_lookups


class CacheFullError(Exception):
    """Raised when cache is full and eviction is disabled."""
    pass


class DNSCache:
    """LRU DNS cache with TTL expiration and bounded capacity.

    Features:
    - Per-entry TTL with lazy expiration on access
    - LRU eviction when capacity is reached
    - Hit/miss statistics
    - Bulk invalidation by domain pattern
    - Periodic purge of expired entries
    """

    def __init__(self, capacity: int = 10000, default_ttl: float = 300.0):
        if capacity < 1:
            raise ValueError("Capacity must be at least 1")
        if default_ttl <= 0:
            raise ValueError("Default TTL must be positive")

        self.capacity = capacity
        self.default_ttl = default_ttl
        self._entries: OrderedDict[str, DNSRecord] = OrderedDict()
        self._stats = CacheStats()

    @property
    def size(self) -> int:
        """Current number of entries (including possibly expired)."""
        return len(self._entries)

    @property
    def stats(self) -> CacheStats:
        return self._stats

    def lookup(self, name: str, record_type: RecordType = RecordType.A) -> str | None:
        """Look up a DNS record. Returns None on miss or expiration."""
        key = f"{name}:{record_type.value}"
        record = self._entries.get(key)

        if record is None:
            self._stats.misses += 1
            return None

        if record.is_expired:
            del self._entries[key]
            self._stats.expirations += 1
            self._stats.misses += 1
            return None

        # Move to end (most recently used)
        self._entries.move_to_end(key)
        self._stats.hits += 1
        return record.value

    @runtime_guard(DNSCacheSpec, state_extractor=lambda self: {
        'entries': self.size,
        'capacity': self.capacity,
        'hits': self.stats.hits,
        'misses': self.stats.misses,
    })
    def insert(
        self,
        name: str,
        value: str,
        record_type: RecordType = RecordType.A,
        ttl: float | None = None,
    ) -> None:
        """Insert or update a DNS record."""
        key = f"{name}:{record_type.value}"
        actual_ttl = ttl if ttl is not None else self.default_ttl

        # If key already exists, update in place
        if key in self._entries:
            self._entries[key] = DNSRecord(
                name=name, record_type=record_type,
                value=value, ttl=actual_ttl,
            )
            self._entries.move_to_end(key)
            return

        # Evict if at capacity
        while len(self._entries) >= self.capacity:
            self._evict_lru()

        self._entries[key] = DNSRecord(
            name=name, record_type=record_type,
            value=value, ttl=actual_ttl,
        )
        self._stats.insertions += 1

    def invalidate(self, name: str, record_type: RecordType | None = None) -> int:
        """Remove entries matching a name (and optionally type). Returns count removed."""
        to_remove = []
        for key, record in self._entries.items():
            if record.name == name:
                if record_type is None or record.record_type == record_type:
                    to_remove.append(key)

        for key in to_remove:
            del self._entries[key]
        return len(to_remove)

    @runtime_guard(DNSCacheSpec, state_extractor=lambda self: {
        'entries': self.size,
        'capacity': self.capacity,
        'hits': self.stats.hits,
        'misses': self.stats.misses,
    })
    def flush(self) -> int:
        """Remove all entries. Returns count removed."""
        count = len(self._entries)
        self._entries.clear()
        return count

    def purge_expired(self) -> int:
        """Remove all expired entries. Returns count purged."""
        expired = [k for k, v in self._entries.items() if v.is_expired]
        for key in expired:
            del self._entries[key]
            self._stats.expirations += 1
        return len(expired)

    @runtime_guard(DNSCacheSpec, state_extractor=lambda self: {
        'entries': self.size,
        'capacity': self.capacity,
        'hits': self.stats.hits,
        'misses': self.stats.misses,
    })
    def _evict_lru(self) -> None:
        """Evict the least recently used entry."""
        if self._entries:
            self._entries.popitem(last=False)
            self._stats.evictions += 1
