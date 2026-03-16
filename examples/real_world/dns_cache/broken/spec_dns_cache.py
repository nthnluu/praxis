"""Broken DNS cache spec — insert doesn't check capacity.

Bug: cache_miss_insert allows inserting without checking
entries + 1 <= capacity. This violates the bounded invariant.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, Nat
from praxis.decorators import require


class BrokenDNSCacheSpec(Spec):
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
        """BUG: No capacity check before insert."""
        # Missing: require(self.entries + 1 <= self.capacity)
        require(self.misses + 1 <= 1000000)
        self.entries += 1
        self.misses += 1

    @transition
    def cache_hit(self):
        require(self.entries > 0)
        require(self.hits + 1 <= 1000000)
        self.hits += 1

    @transition
    def evict(self, count: BoundedInt[1, 100]):
        require(self.entries >= count)
        self.entries -= count
