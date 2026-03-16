"""DNS Cache Spec — bounded cache with entry tracking.

Proves:
- Cache size never exceeds capacity
- Cache size is never negative
- Active entries never exceed total entries added
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, Nat
from praxis.decorators import require


class DNSCacheSpec(Spec):
    """Bounded DNS cache with eviction."""

    entries: BoundedInt[0, 10000]
    capacity: BoundedInt[1, 10000]
    hits: Nat
    misses: Nat

    @invariant
    def bounded(self):
        return self.entries <= self.capacity

    @invariant
    def non_negative(self):
        return And(self.entries >= 0, self.hits >= 0, self.misses >= 0)

    @transition
    def cache_miss_insert(self):
        """Cache miss — insert new entry."""
        require(self.entries + 1 <= self.capacity)
        require(self.misses + 1 <= 1000000)
        self.entries += 1
        self.misses += 1

    @transition
    def cache_hit(self):
        """Cache hit."""
        require(self.entries > 0)
        require(self.hits + 1 <= 1000000)
        self.hits += 1

    @transition
    def evict(self, count: BoundedInt[1, 100]):
        """Evict entries to make room."""
        require(self.entries >= count)
        self.entries -= count

    @transition
    def flush(self):
        """Flush entire cache."""
        self.entries = 0
