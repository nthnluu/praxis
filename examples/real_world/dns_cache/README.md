# DNS Cache

## The Problem

DNS resolution is one of the most latency-sensitive operations in any networked application. Every HTTP request, database connection, and service call starts with a DNS lookup. Without caching, each lookup hits the recursive resolver, adding 10-100ms of latency. With caching, lookups resolve in microseconds — but the cache introduces its own failure modes.

The most dangerous DNS cache bug is unbounded growth. A cache without a hard capacity limit grows until the process runs out of memory. This is especially insidious because DNS entries accumulate slowly over hours or days of normal operation, and the OOM kill happens at 3 AM when traffic patterns shift and the working set suddenly expands. The second class of bugs involves stale entries: a cache that ignores TTLs serves outdated records after a DNS change, routing traffic to decommissioned servers.

A formal specification lets us prove that the cache never exceeds its capacity — regardless of the insertion pattern, eviction timing, or flush sequence — and that the hit/miss counters stay consistent.

## The Implementation

`cache.py` — A production-style `DNSCache` using:
- **`collections.OrderedDict`** for O(1) LRU eviction (move-to-end on access, pop-first on evict)
- **`dataclasses`** for `DNSRecord` (with TTL tracking) and `CacheStats`
- **`enum.Enum`** for DNS record types (A, AAAA, CNAME, MX, TXT)

Key methods:
```python
class DNSCache:
    def lookup(self, name: str, record_type: RecordType) -> str | None
    def insert(self, name: str, value: str, record_type: RecordType, ttl: float) -> None
    def invalidate(self, name: str) -> int
    def flush(self) -> int
    def purge_expired(self) -> int
```

The cache uses lazy expiration: expired entries are removed on `lookup()`, not on a timer. This avoids background threads while keeping reads fast. When the cache is full, `insert()` evicts the least-recently-used entry before adding the new one.

## The Spec

`spec_dns_cache.py` models the cache with four counters:

1. **`bounded`**: `entries <= capacity`. The cache never exceeds its configured size limit.
2. **`non_negative`**: All counters (entries, hits, misses) are non-negative.

Transitions:
- **`cache_miss_insert`**: Requires `entries + 1 <= capacity` before inserting
- **`cache_hit`**: Increments hit counter (requires entries > 0)
- **`evict(count)`**: Removes entries (requires entries >= count)
- **`flush`**: Sets entries to 0

## Three Ways to Connect Spec and Implementation

### 1. Static verification (recommended first step)

```bash
praxis check examples/real_world/dns_cache/
```

### 2. Fuzz testing in pytest (recommended for CI)

The cleanest approach -- the spec connection lives in the test, not the implementation:

```python
import praxis

result = praxis.fuzz(
    cache,
    DNSCacheSpec,
    state_extractor=lambda self: {
        'entries': self.size,
        'capacity': self.capacity,
        'hits': self.stats.hits,
        'misses': self.stats.misses,
    },
    operations=[
        lambda c: c.insert(f"host-{random.randint(1,100)}.com", "1.2.3.4", RecordType.A, 60),
        lambda c: c.lookup(f"host-{random.randint(1,100)}.com", RecordType.A),
        lambda c: c.flush(),
    ],
)
assert result.passed, result
```

### 3. Runtime monitoring (for production)

```python
import praxis

praxis.monitor(
    DNSCache,
    DNSCacheSpec,
    state_extractor=lambda self: {
        'entries': self.size, 'capacity': self.capacity,
        'hits': self.stats.hits, 'misses': self.stats.misses,
    },
    methods=["insert", "flush", "invalidate"],
    mode="log",
)
```

### 4. Per-method decorators (legacy, still supported)

The implementation currently uses `@runtime_guard` on `insert`, `_evict_lru`, and `flush`:

```python
@runtime_guard(DNSCacheSpec, state_extractor=lambda self: {
    'entries': self.size, 'capacity': self.capacity,
    'hits': self.stats.hits, 'misses': self.stats.misses,
})
def insert(self, name, value, record_type, ttl) -> None: ...
```

If `insert` somehow adds an entry without evicting when at capacity, the `bounded` invariant (`entries <= capacity`) fires immediately instead of silently growing until OOM.

## What Praxis Proves

For **every possible** combination of entries, capacity, hits, and misses:

1. The cache never holds more entries than its capacity
2. All counters remain non-negative
3. Eviction can't remove more entries than exist
4. Flush always brings the cache to a clean state

## The Bug Praxis Catches

In `broken/spec_dns_cache.py`, `cache_miss_insert` is missing the capacity check:

```python
@transition
def cache_miss_insert(self, dummy: BoundedInt[0, 0]):
    # Missing: require(self.entries + 1 <= self.capacity)
    self.entries += 1
    self.misses += 1
```

Praxis finds: a cache at `capacity=1` with `entries=1` can insert another entry, pushing `entries` to 2 — violating `entries <= capacity`.

## Run It

```bash
pytest examples/real_world/dns_cache/ -v
praxis check examples/real_world/dns_cache/
praxis check examples/real_world/dns_cache/broken/
```
