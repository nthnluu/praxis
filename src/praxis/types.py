"""Praxis type system — scalar types that map to Z3 sorts."""

from __future__ import annotations

import z3


class _BoundedIntMeta(type):
    """Metaclass enabling BoundedInt[lo, hi] subscript syntax."""

    def __getitem__(cls, bounds: tuple[int, int]) -> type:
        if not isinstance(bounds, tuple) or len(bounds) != 2:
            raise TypeError("BoundedInt requires exactly two bounds: BoundedInt[lo, hi]")
        lo, hi = bounds
        if not isinstance(lo, int) or not isinstance(hi, int):
            raise TypeError(
                f"BoundedInt bounds must be integers, got {type(lo).__name__} and {type(hi).__name__}"
            )
        if lo > hi:
            raise ValueError(
                f"BoundedInt lower bound ({lo}) must be <= upper bound ({hi})"
            )
        ns = {
            "_lo": lo,
            "_hi": hi,
            "_praxis_type": "BoundedInt",
        }
        new_cls = type(f"BoundedInt[{lo}, {hi}]", (BoundedInt,), ns)
        new_cls.to_z3 = classmethod(lambda cls, name: _bounded_int_to_z3(cls, name))
        return new_cls


def _bounded_int_to_z3(cls, name: str) -> tuple[z3.ArithRef, list]:
    var = z3.Int(name)
    constraints = [var >= cls._lo, var <= cls._hi]
    return var, constraints


class BoundedInt(metaclass=_BoundedIntMeta):
    """An integer constrained to [lo, hi]. Usage: BoundedInt[0, 100]"""

    _praxis_type = "BoundedInt"

    @classmethod
    def to_z3(cls, name: str) -> tuple[z3.ArithRef, list]:
        raise TypeError("Cannot call to_z3 on unparameterized BoundedInt. Use BoundedInt[lo, hi].")


# Convenience types — users never think about bounds
Nat = BoundedInt[0, 2**63 - 1]
Int = BoundedInt[-2**63, 2**63 - 1]
PosInt = BoundedInt[1, 2**63 - 1]


# ============================================================
# Intent types — model data structures by their properties
# ============================================================
# These are sugar over BoundedInt. Under the hood, Praxis models
# the numeric PROPERTY of the data structure (length, count, size),
# not the contents. The developer writes their intent; Praxis
# verifies the invariants over that intent.

class _IntentTypeMeta(type):
    """Metaclass for intent types that support optional parameterization."""

    def __getitem__(cls, bounds):
        if not isinstance(bounds, tuple) or len(bounds) != 2:
            raise TypeError(f"{cls.__name__} requires [min, max] bounds")
        lo, hi = bounds
        # Create a BoundedInt with the given bounds
        base = BoundedInt[lo, hi]
        # Carry forward the intent name for better error messages
        new_cls = type(f"{cls.__name__}[{lo}, {hi}]", (base,), {
            "_intent_type": cls.__name__,
        })
        return new_cls


# Strings — modeled by length
class StringLength(metaclass=_IntentTypeMeta):
    """Length of a string. Use when you care about string emptiness or max length.

    Usage:
        name: StringLength[1, 255]    # non-empty, max 255 chars
        bio: StringLength[0, 1000]    # optional, max 1000 chars
    """
    _praxis_type = "BoundedInt"


NonEmptyString = BoundedInt[1, 2**16]  # string length >= 1


# Lists/Arrays — modeled by count
class ListLength(metaclass=_IntentTypeMeta):
    """Number of items in a list/array.

    Usage:
        cart_items: ListLength[0, 100]     # up to 100 items
        gpu_jobs: ListLength[0, 1000]      # up to 1000 jobs
    """
    _praxis_type = "BoundedInt"


# Dicts/Maps — modeled by entry count
class MapSize(metaclass=_IntentTypeMeta):
    """Number of entries in a dict/map.

    Usage:
        cache_entries: MapSize[0, 10000]
        active_sessions: MapSize[0, 100000]
    """
    _praxis_type = "BoundedInt"


# Sets — modeled by cardinality
class SetSize(metaclass=_IntentTypeMeta):
    """Number of elements in a set.

    Usage:
        unique_users: SetSize[0, 1000000]
        blocked_ips: SetSize[0, 10000]
    """
    _praxis_type = "BoundedInt"


# Byte sizes — modeled as integer byte/KB/MB counts
class ByteSize(metaclass=_IntentTypeMeta):
    """Size in bytes.

    Usage:
        payload_bytes: ByteSize[0, 10_000_000]   # up to 10MB
        buffer_size: ByteSize[1, 65536]           # 1 byte to 64KB
    """
    _praxis_type = "BoundedInt"


# Percentage/ratio — modeled as integer basis points or percentage
class Percentage(metaclass=_IntentTypeMeta):
    """Percentage value (0-100).

    Usage:
        cpu_usage: Percentage[0, 100]
        completion: Percentage[0, 100]
    """
    _praxis_type = "BoundedInt"


class _BoundedFloatMeta(type):
    """Metaclass enabling BoundedFloat[lo, hi] subscript syntax."""

    def __getitem__(cls, bounds: tuple[float, float]) -> type:
        if not isinstance(bounds, tuple) or len(bounds) != 2:
            raise TypeError("BoundedFloat requires exactly two bounds: BoundedFloat[lo, hi]")
        lo, hi = bounds
        if not isinstance(lo, (int, float)) or not isinstance(hi, (int, float)):
            raise TypeError(
                f"BoundedFloat bounds must be numeric, got {type(lo).__name__} and {type(hi).__name__}"
            )
        if lo > hi:
            raise ValueError(
                f"BoundedFloat lower bound ({lo}) must be <= upper bound ({hi})"
            )
        lo_f, hi_f = float(lo), float(hi)
        ns = {
            "_lo": lo_f,
            "_hi": hi_f,
            "_praxis_type": "BoundedFloat",
        }
        new_cls = type(f"BoundedFloat[{lo}, {hi}]", (BoundedFloat,), ns)
        new_cls.to_z3 = classmethod(lambda cls, name: _bounded_float_to_z3(cls, name))
        return new_cls


def _bounded_float_to_z3(cls, name: str) -> tuple[z3.ArithRef, list]:
    var = z3.Real(name)
    constraints = [var >= z3.RealVal(cls._lo), var <= z3.RealVal(cls._hi)]
    return var, constraints


class BoundedFloat(metaclass=_BoundedFloatMeta):
    """A real number constrained to [lo, hi]. Usage: BoundedFloat[0.0, 1.0]"""

    _praxis_type = "BoundedFloat"

    @classmethod
    def to_z3(cls, name: str) -> tuple[z3.ArithRef, list]:
        raise TypeError("Cannot call to_z3 on unparameterized BoundedFloat. Use BoundedFloat[lo, hi].")


class Bool:
    """A boolean type for spec state fields."""

    _praxis_type = "Bool"

    @classmethod
    def to_z3(cls, name: str) -> tuple[z3.BoolRef, list]:
        return z3.Bool(name), []


class _PraxisEnumMeta(type):
    """Metaclass for PraxisEnum that provides Z3 integration."""

    def __new__(mcs, name, bases, namespace):
        cls = super().__new__(mcs, name, bases, namespace)
        if name == "PraxisEnum":
            return cls

        # Collect enum values (class-level int attributes)
        values = {}
        for k, v in namespace.items():
            if not k.startswith("_") and isinstance(v, int):
                values[k] = v

        if values:
            cls._enum_values = values
            cls._enum_names = {v: k for k, v in values.items()}
            lo = min(values.values())
            hi = max(values.values())
            cls._lo = lo
            cls._hi = hi
            cls._praxis_type = "Enum"
            cls.to_z3 = classmethod(lambda cls, name: _enum_to_z3(cls, name))

        return cls


def _enum_to_z3(cls, name: str) -> tuple[z3.ArithRef, list]:
    """Convert an enum type to a Z3 variable with membership constraints."""
    var = z3.Int(name)
    constraints = [z3.Or(*[var == v for v in cls._enum_values.values()])]
    return var, constraints


class PraxisEnum(metaclass=_PraxisEnumMeta):
    """Base class for Praxis enum types.

    Usage:
        class Status(PraxisEnum):
            PENDING = 0
            ACTIVE = 1
            CLOSED = 2
    """
    _praxis_type = "Enum"

    @classmethod
    def to_z3(cls, name: str) -> tuple[z3.ArithRef, list]:
        raise TypeError("Cannot call to_z3 on base PraxisEnum. Define a subclass with values.")


def is_praxis_type(t: type) -> bool:
    """Check if a type is a Praxis type."""
    return hasattr(t, "_praxis_type")
