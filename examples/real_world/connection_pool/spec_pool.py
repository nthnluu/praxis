"""Connection Pool Spec — database connection management.

Proves:
- Active connections never exceed pool max size
- Active connections are never negative
- Checkout/checkin balance is maintained
"""

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require


class ConnectionPoolSpec(Spec):
    """Database connection pool with bounded size."""

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
        """Create a new idle connection."""
        require(self.active + self.idle + 1 <= self.max_size)
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
