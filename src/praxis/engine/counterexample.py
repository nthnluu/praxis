"""Counterexample formatting — human-readable and JSON output."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Counterexample:
    """A counterexample from Z3 showing a property violation."""
    spec_name: str
    property_name: str
    kind: str  # 'invariant_violation' or 'invariant_inconsistency'
    transition: str | None = None
    before: dict[str, Any] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    explanation: str = ""
    message: str | None = None  # Custom message from @invariant(message="...")

    def to_human(self) -> str:
        """Format as human-readable string."""
        lines = []
        label = "INVARIANT VIOLATED" if self.transition else "INVARIANT UNSATISFIABLE"
        lines.append(f"{label}: {self.property_name}")
        if self.message:
            lines.append(f"  {self.message}")
        lines.append("")

        if self.before:
            lines.append("  Counterexample:")
            for name, val in sorted(self.before.items()):
                lines.append(f"    {name} = {val}")

        if self.inputs:
            lines.append("")
            lines.append("  Inputs:")
            for name, val in sorted(self.inputs.items()):
                lines.append(f"    {name} = {val}")

        if self.after and self.transition:
            lines.append("")
            lines.append(f"  After transition `{self.transition}`:")
            for name, val in sorted(self.after.items()):
                lines.append(f"    {name}' = {val}")

        if self.explanation:
            lines.append("")
            lines.append(f"  {self.explanation}")

        return "\n".join(lines)

    def to_json(self) -> dict[str, Any]:
        """Format as structured JSON-serializable dict."""
        result: dict[str, Any] = {
            "status": "FAIL",
            "spec": self.spec_name,
            "property": self.property_name,
            "kind": self.kind,
        }
        if self.transition:
            result["transition"] = self.transition
        result["counterexample"] = {
            "before": self.before or {},
            "inputs": self.inputs or {},
            "after": self.after or {},
        }
        if self.explanation:
            result["explanation"] = self.explanation
        if self.message:
            result["message"] = self.message
        return result


def extract_counterexample_from_model(
    model,
    spec_name: str,
    property_name: str,
    state_vars: dict,
    param_vars: dict | None = None,
    primed_vars: dict | None = None,
    transition_name: str | None = None,
) -> Counterexample:
    """Extract a Counterexample from a Z3 model.

    Args:
        model: Z3 model (from solver.model())
        spec_name: Name of the spec class
        property_name: Name of the invariant/property
        state_vars: Dict of {name: z3_var} for state variables
        param_vars: Dict of {name: z3_var} for transition parameters
        primed_vars: Dict of {name: z3_var} for primed state variables
        transition_name: Name of the transition (if applicable)
    """
    before = {}
    for name, var in state_vars.items():
        val = model.eval(var, model_completion=True)
        before[name] = _z3_val_to_python(val)

    inputs = {}
    if param_vars:
        for name, var in param_vars.items():
            val = model.eval(var, model_completion=True)
            inputs[name] = _z3_val_to_python(val)

    after = {}
    if primed_vars:
        for name, var in primed_vars.items():
            val = model.eval(var, model_completion=True)
            after[name] = _z3_val_to_python(val)

    kind = "invariant_violation" if transition_name else "invariant_inconsistency"

    return Counterexample(
        spec_name=spec_name,
        property_name=property_name,
        kind=kind,
        transition=transition_name,
        before=before,
        inputs=inputs,
        after=after,
    )


def _z3_val_to_python(val) -> int | float | bool | str:
    """Convert a Z3 value to a Python value."""
    import z3
    if z3.is_int_value(val):
        return val.as_long()
    if z3.is_rational_value(val):
        num = val.numerator_as_long()
        den = val.denominator_as_long()
        if den == 1:
            return num
        return num / den
    if z3.is_true(val):
        return True
    if z3.is_false(val):
        return False
    return str(val)
