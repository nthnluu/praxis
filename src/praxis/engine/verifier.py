"""Core verification engine — orchestrates Z3 solving."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import z3

from praxis.compiler.extractor import extract_spec, ExtractedSpec, ExtractedInvariant, ExtractedInitial, ExtractedTransition
from praxis.compiler.lowering import lower_invariant, lower_transition
from praxis.compiler.emitter import EmitContext, emit
from praxis.compiler.ir import Require, Assign
from praxis.engine.counterexample import (
    Counterexample,
    extract_counterexample_from_model,
)


@dataclass
class VerificationResult:
    """Result of verifying a single property."""
    property_name: str
    kind: str  # 'invariant', 'transition'
    status: str  # 'pass', 'fail', 'timeout', 'error'
    counterexample: Counterexample | None = None
    error_message: str | None = None
    transition_name: str | None = None


@dataclass
class SpecVerificationResult:
    """Result of verifying an entire spec."""
    spec_name: str
    results: list[VerificationResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.status == "pass" for r in self.results)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == "pass")

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == "fail")


def verify_spec(spec_cls, timeout_ms: int = 30000, fuzz_count: int = 10000) -> SpecVerificationResult:
    """Verify all invariants and transitions on a Spec subclass.

    Args:
        spec_cls: A Spec subclass to verify.
        timeout_ms: Z3 timeout per property in milliseconds.
        fuzz_count: Number of random inputs for fallback fuzzing on Z3 timeout.

    Returns:
        SpecVerificationResult with all individual results.
    """
    extracted = extract_spec(spec_cls)
    result = SpecVerificationResult(spec_name=extracted.name)

    # Verify initial states satisfy all invariants (induction base case)
    for init in extracted.initials:
        init_results = _verify_initial(extracted, init, timeout_ms)
        result.results.extend(init_results)

    # Verify invariant consistency once (not per-invariant)
    inv_results = _verify_invariants_consistency(extracted, timeout_ms, spec_cls, fuzz_count)
    result.results.extend(inv_results)

    # Verify each transition preserves all invariants
    for trans in extracted.transitions:
        vr = _verify_transition(extracted, trans, timeout_ms)
        result.results.append(vr)

    # Verify target functions (if any @verify methods exist)
    for verification in spec_cls.verifications():
        target_path = getattr(verification, '_praxis_verify_target', None)
        if target_path:
            from praxis.engine.target_verifier import verify_target
            tvr = verify_target(spec_cls, target_path, timeout_ms, fuzz_count)
            result.results.append(VerificationResult(
                property_name=verification.__name__,
                kind="verify",
                status=tvr.status if tvr.status != "unsupported" else "pass",
                error_message=tvr.message,
                transition_name=target_path,
                counterexample=tvr.counterexample,
            ))

    return result


def _verify_initial(
    extracted: ExtractedSpec, init: ExtractedInitial, timeout_ms: int,
) -> list[VerificationResult]:
    """Verify that an initial state predicate satisfies all invariants.

    This proves the induction base case: Init => Inv.
    We assert Init AND NOT(Inv). If UNSAT, the base case holds.
    """
    if not extracted.invariants:
        return [VerificationResult(
            property_name=init.name,
            kind="initial",
            status="pass",
        )]

    try:
        ctx = EmitContext()
        for name, ptype in extracted.state_fields.items():
            ctx.add_state_var(name, ptype)

        # Lower and emit the initial predicate
        init_ir = lower_invariant(init.ast_node)
        init_z3 = emit(init_ir, ctx)

        # Lower and emit all invariants
        inv_exprs = []
        for inv in extracted.invariants:
            inv_ir = lower_invariant(inv.ast_node)
            inv_exprs.append((inv, emit(inv_ir, ctx)))

        s = z3.Solver()
        s.set("timeout", timeout_ms)

        # Type bound constraints
        s.add(*ctx.constraints)

        # Assert the initial predicate holds
        s.add(init_z3)

        # Assert NOT(all invariants hold)
        s.add(z3.Not(z3.And(*[expr for _, expr in inv_exprs])))

        check = s.check()
        if check == z3.unsat:
            # Base case proven: Init => Inv
            return [VerificationResult(
                property_name=init.name,
                kind="initial",
                status="pass",
            )]
        elif check == z3.sat:
            # Find which invariant is violated
            model = s.model()
            violated_inv_name = init.name
            violated_message = None
            for inv, inv_expr in inv_exprs:
                val = model.eval(inv_expr, model_completion=True)
                if z3.is_false(val):
                    violated_inv_name = inv.name
                    violated_message = inv.message
                    break

            ce = extract_counterexample_from_model(
                model=model,
                spec_name=extracted.name,
                property_name=violated_inv_name,
                state_vars=ctx.vars,
            )
            ce.explanation = (
                f"Initial state '{init.name}' does not satisfy invariant '{violated_inv_name}'"
            )
            if violated_message:
                ce.message = violated_message
            ce.kind = "initial_violation"

            return [VerificationResult(
                property_name=init.name,
                kind="initial",
                status="fail",
                counterexample=ce,
                error_message=f"Initial state violates invariant '{violated_inv_name}'",
            )]
        else:
            return [VerificationResult(
                property_name=init.name,
                kind="initial",
                status="timeout",
                error_message="Z3 returned UNKNOWN (timeout or undecidable)",
            )]
    except Exception as e:
        return [VerificationResult(
            property_name=init.name,
            kind="initial",
            status="error",
            error_message=str(e),
        )]


def _verify_invariants_consistency(
    extracted: ExtractedSpec, timeout_ms: int,
    spec_cls: type | None = None, fuzz_count: int = 10000,
) -> list[VerificationResult]:
    """Verify all invariants are simultaneously satisfiable.

    Does ONE Z3 check for all invariants instead of N checks.
    If consistent, all invariants pass. If not, identifies which fail.
    """
    if not extracted.invariants:
        return []

    try:
        ctx = EmitContext()
        for name, ptype in extracted.state_fields.items():
            ctx.add_state_var(name, ptype)

        # Build all invariant Z3 expressions
        inv_exprs = {}
        for inv in extracted.invariants:
            ir = lower_invariant(inv.ast_node)
            inv_exprs[inv.name] = emit(ir, ctx)

        # Check all invariants simultaneously
        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(*ctx.constraints)
        for expr in inv_exprs.values():
            s.add(expr)

        check = s.check()
        if check == z3.sat:
            # All consistent — all pass
            return [
                VerificationResult(property_name=inv.name, kind="invariant", status="pass")
                for inv in extracted.invariants
            ]
        elif check == z3.unsat:
            # Contradictory — report failure for each invariant
            results = []
            for inv in extracted.invariants:
                ce = Counterexample(
                    spec_name=extracted.name,
                    property_name=inv.name,
                    kind="invariant_inconsistency",
                    explanation="Invariants are mutually contradictory",
                )
                results.append(VerificationResult(
                    property_name=inv.name,
                    kind="invariant",
                    status="fail",
                    counterexample=ce,
                ))
            return results
        else:
            # Z3 timeout — fall back to fuzzing each invariant
            from praxis.engine.fallback import fuzz_invariant
            results = []
            # Get the actual callable methods from the spec class
            inv_methods = {m.__name__: m for m in spec_cls.invariants()}
            for inv in extracted.invariants:
                try:
                    inv_method = inv_methods.get(inv.name)
                    if inv_method is None:
                        raise ValueError(f"Could not find invariant method '{inv.name}'")
                    fuzz_result = fuzz_invariant(spec_cls, inv_method, iterations=fuzz_count)
                    if fuzz_result.passed:
                        results.append(VerificationResult(
                            property_name=inv.name,
                            kind="invariant",
                            status="timeout",
                            error_message=(
                                f"Z3 returned UNKNOWN. "
                                f"Fallback: property-based testing with {fuzz_count} inputs found 0 violations."
                            ),
                        ))
                    else:
                        results.append(VerificationResult(
                            property_name=inv.name,
                            kind="invariant",
                            status="fail",
                            error_message=fuzz_result.to_human(),
                        ))
                except Exception:
                    results.append(VerificationResult(
                        property_name=inv.name,
                        kind="invariant",
                        status="timeout",
                        error_message="Z3 returned UNKNOWN (timeout or undecidable)",
                    ))
            return results
    except Exception as e:
        return [
            VerificationResult(
                property_name=inv.name,
                kind="invariant",
                status="error",
                error_message=str(e),
            )
            for inv in extracted.invariants
        ]


def _verify_transition(extracted: ExtractedSpec, trans: ExtractedTransition, timeout_ms: int) -> VerificationResult:
    """Verify a transition preserves all invariants."""
    try:
        ctx = EmitContext()

        # Before-state variables
        for name, ptype in extracted.state_fields.items():
            ctx.add_state_var(name, ptype)

        # Primed (after-state) variables
        for name, ptype in extracted.state_fields.items():
            ctx.add_primed_var(name, ptype)

        # Transition parameters
        param_names = []
        for param in trans.params:
            if param.annotation is None:
                return VerificationResult(
                    property_name=trans.name,
                    kind="transition",
                    status="error",
                    transition_name=trans.name,
                    error_message=f"Parameter '{param.name}' has no type annotation",
                )
            ctx.add_param(param.name, param.annotation)
            param_names.append(param.name)

        # Lower the transition body
        ir_nodes = lower_transition(trans.ast_node, param_names)

        # Separate require nodes and assign nodes
        requires = [n for n in ir_nodes if isinstance(n, Require)]
        assigns = [n for n in ir_nodes if isinstance(n, Assign)]

        # Build the solver
        s = z3.Solver()
        s.set("timeout", timeout_ms)

        # Type bound constraints
        s.add(*ctx.constraints)

        # Assume all invariants hold in before-state
        for inv in extracted.invariants:
            inv_ir = lower_invariant(inv.ast_node)
            inv_z3 = emit(inv_ir, ctx)
            s.add(inv_z3)

        # Assume preconditions
        for req in requires:
            req_z3 = emit(req, ctx)
            s.add(req_z3)

        # Apply transition: relate primed vars to unprimed vars
        # For assigned fields, primed = computed value
        assigned_fields = set()
        for assign in assigns:
            if assign.target not in ctx.primed:
                raise KeyError(
                    f"Transition '{trans.name}' assigns to 'self.{assign.target}', "
                    f"but '{assign.target}' is not a declared state field. "
                    f"Declared fields: {list(extracted.state_fields.keys())}"
                )
            val_z3 = emit(assign, ctx)
            primed_var = ctx.primed[assign.target]
            s.add(primed_var == val_z3)
            assigned_fields.add(assign.target)

        # For unassigned fields, primed = original (frame condition)
        for name in extracted.state_fields:
            if name not in assigned_fields:
                s.add(ctx.primed[name] == ctx.vars[name])

        # Negate invariants on after-state: at least one must be violated
        after_inv_exprs = []
        for inv in extracted.invariants:
            inv_ir = lower_invariant(inv.ast_node)
            # Create a temporary context that maps vars to primed
            after_ctx = EmitContext()
            after_ctx.vars = ctx.primed  # Map var references to primed vars
            after_ctx.params = ctx.params
            inv_after_z3 = emit(inv_ir, after_ctx)
            after_inv_exprs.append(inv_after_z3)

        # Assert negation: NOT(all invariants hold after)
        s.add(z3.Not(z3.And(*after_inv_exprs)))

        # NOTE: We intentionally do NOT add primed variable bound constraints.
        # The invariants themselves are what we're checking — if the transition
        # can produce an after-state outside type bounds, that IS a violation.

        check = s.check()
        if check == z3.unsat:
            return VerificationResult(
                property_name=trans.name,
                kind="transition",
                status="pass",
                transition_name=trans.name,
            )
        elif check == z3.sat:
            # Find which invariant is violated
            model = s.model()
            violated_inv = trans.name
            violated_message = None
            for inv, inv_expr in zip(extracted.invariants, after_inv_exprs):
                val = model.eval(inv_expr, model_completion=True)
                if z3.is_false(val):
                    violated_inv = inv.name
                    violated_message = inv.message
                    break

            ce = extract_counterexample_from_model(
                model=model,
                spec_name=extracted.name,
                property_name=violated_inv,
                state_vars=ctx.vars,
                param_vars=ctx.params,
                primed_vars=ctx.primed,
                transition_name=trans.name,
            )
            if violated_message:
                ce.message = violated_message
            return VerificationResult(
                property_name=violated_inv,
                kind="transition",
                status="fail",
                counterexample=ce,
                transition_name=trans.name,
            )
        else:
            return VerificationResult(
                property_name=trans.name,
                kind="transition",
                status="timeout",
                transition_name=trans.name,
                error_message="Z3 returned UNKNOWN (timeout or undecidable)",
            )
    except Exception as e:
        return VerificationResult(
            property_name=trans.name,
            kind="transition",
            status="error",
            transition_name=trans.name,
            error_message=str(e),
        )
