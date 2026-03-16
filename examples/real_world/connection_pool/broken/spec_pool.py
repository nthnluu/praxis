"""Broken connection pool spec — create_connection doesn't check capacity.

This spec is identical to the correct one except that the create_connection
transition omits the guard `active + idle + 1 <= max_size`. Without this
check, the pool can grow beyond its configured maximum, violating the
`active_bounded` invariant.

This models a real bug: under concurrent load, if the "is there room?"
check is missing or racy, the pool can silently exceed its limit, opening
more database connections than the server allows.
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class BrokenConnectionPoolSpec(Spec):
    """Connection pool spec where create_connection has no capacity guard."""

    max_size: BoundedInt[1, 100]
    active: BoundedInt[0, 100]        # Connections in use
    idle: BoundedInt[0, 100]          # Connections available
    total_created: BoundedInt[0, 100] # Total connections ever created

    @invariant
    def active_bounded(self):
        """Active connections never exceed pool size."""
        return self.active + self.idle <= self.max_size

    @invariant
    def non_negative(self):
        """All counters are non-negative."""
        return And(self.active >= 0, self.idle >= 0)

    @invariant
    def total_consistent(self):
        """Total created = active + idle."""
        return self.total_created == self.active + self.idle

    @transition
    def checkout(self):
        """Check out a connection from the pool."""
        require(self.idle > 0)
        self.idle -= 1
        self.active += 1

    @transition
    def checkin(self):
        """Return a connection to the pool."""
        require(self.active > 0)
        self.active -= 1
        self.idle += 1

    @transition
    def create_connection(self):
        """BUG: Create a new connection WITHOUT checking capacity."""
        # Missing: require(self.active + self.idle + 1 <= self.max_size)
        require(self.total_created + 1 <= 100)
        self.idle += 1
        self.total_created += 1

    @transition
    def destroy_idle(self):
        """Destroy an idle connection."""
        require(self.idle > 0)
        require(self.total_created > 0)
        self.idle -= 1
        self.total_created -= 1
