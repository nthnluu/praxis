"""BROKEN circuit breaker — trip_open doesn't require threshold reached.

Bug: The trip_open transition allows opening the circuit even when
failure_count hasn't reached the threshold. This violates the invariant
that OPEN state implies failures >= threshold.
"""

# This file exists to document the broken implementation.
# The spec in broken/spec_circuit_breaker.py models the bug.
