"""Spec base class — collects state fields, invariants, and transitions."""

from __future__ import annotations

from praxis.types import is_praxis_type


class Spec:
    """Base class for formal specifications.

    Subclasses declare state fields as type annotations using Praxis types,
    and define @invariant, @transition, and @verify methods.
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        # Collect state fields from type annotations (including inherited)
        cls._state_fields = {}
        for klass in reversed(cls.__mro__):
            for name, ann in getattr(klass, "__annotations__", {}).items():
                if is_praxis_type(ann):
                    cls._state_fields[name] = ann

        # Collect decorated methods
        cls._invariants = []
        cls._transitions = []
        cls._verifications = []
        cls._initials = []

        for attr_name in dir(cls):
            try:
                attr = getattr(cls, attr_name)
            except AttributeError:
                continue
            if not callable(attr):
                continue
            if getattr(attr, "_praxis_invariant", False):
                cls._invariants.append(attr)
            if getattr(attr, "_praxis_transition", False):
                cls._transitions.append(attr)
            if getattr(attr, "_praxis_verify", False):
                cls._verifications.append(attr)
            if getattr(attr, "_praxis_initial", False):
                cls._initials.append(attr)

    @classmethod
    def state_fields(cls) -> dict[str, type]:
        """Return {name: praxis_type} for all state fields."""
        return dict(cls._state_fields)

    @classmethod
    def invariants(cls) -> list:
        """Return all @invariant methods."""
        return list(cls._invariants)

    @classmethod
    def transitions(cls) -> list:
        """Return all @transition methods."""
        return list(cls._transitions)

    @classmethod
    def initials(cls) -> list:
        """Return all @initial methods."""
        return list(cls._initials)

    @classmethod
    def verifications(cls) -> list:
        """Return all @verify methods."""
        return list(cls._verifications)
