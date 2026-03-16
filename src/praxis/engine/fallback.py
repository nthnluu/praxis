"""Fallback — Hypothesis-based fuzzing when Z3 returns UNKNOWN."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any


def generate_random_state(fields: dict[str, Any]) -> dict[str, Any]:
    """Generate a random state dict from spec state fields.

    Shared by fuzz_invariant and target_verifier._fuzz_target.
    """
    values = {}
    for name, ptype in fields.items():
        pt = getattr(ptype, "_praxis_type", None)
        if pt == "BoundedInt":
            values[name] = random.randint(ptype._lo, ptype._hi)
        elif pt == "BoundedFloat":
            values[name] = random.uniform(ptype._lo, ptype._hi)
        elif pt == "Bool":
            values[name] = random.choice([True, False])
        elif pt == "Enum":
            values[name] = random.choice(list(ptype._enum_values.values()))
    return values


@dataclass
class FallbackResult:
    """Result of property-based testing fallback."""
    property_name: str
    iterations: int
    violations: int
    violation_examples: list[dict[str, Any]]

    @property
    def passed(self) -> bool:
        return self.violations == 0

    def to_human(self) -> str:
        msg = (
            f"Symbolic verification timed out. "
            f"Property-based testing with {self.iterations} inputs: "
            f"{self.violations} violations."
        )
        if self.violation_examples:
            msg += "\n  Example violation:"
            for k, v in self.violation_examples[0].items():
                msg += f"\n    {k} = {v}"
        return msg


def generate_strategy(praxis_type: type) -> Any:
    """Generate a Hypothesis strategy from a Praxis type."""
    from hypothesis import strategies as st

    ptype = getattr(praxis_type, "_praxis_type", None)
    if ptype == "BoundedInt":
        return st.integers(min_value=praxis_type._lo, max_value=praxis_type._hi)
    elif ptype == "BoundedFloat":
        return st.floats(
            min_value=praxis_type._lo,
            max_value=praxis_type._hi,
            allow_nan=False,
            allow_infinity=False,
        )
    elif ptype == "Bool":
        return st.booleans()
    elif ptype == "Enum":
        return st.sampled_from(list(praxis_type._enum_values.values()))
    else:
        raise TypeError(f"Cannot generate strategy for type: {praxis_type}")


def fuzz_invariant(
    spec_cls: type,
    invariant_method: Any,
    iterations: int = 10000,
) -> FallbackResult:
    """Fuzz-test an invariant by generating random valid states.

    Args:
        spec_cls: The Spec subclass.
        invariant_method: The @invariant method to test.
        iterations: Number of random inputs to try.

    Returns:
        FallbackResult with violation count and examples.
    """
    fields = spec_cls.state_fields()
    violations = 0
    examples: list[dict[str, Any]] = []

    for _ in range(iterations):
        values = generate_random_state(fields)
        obj = _MockState(values)
        try:
            result = invariant_method(obj)
            if not result:
                violations += 1
                if len(examples) < 5:
                    examples.append(dict(values))
        except Exception:
            violations += 1
            if len(examples) < 5:
                examples.append(dict(values))

    return FallbackResult(
        property_name=invariant_method.__name__,
        iterations=iterations,
        violations=violations,
        violation_examples=examples,
    )


class _MockState:
    """Mock object that provides state field access via attributes."""
    def __init__(self, values: dict[str, Any]):
        for k, v in values.items():
            setattr(self, k, v)
