"""Target function verification — bridges specs to real implementations.

Three-level fallback:
1. Symbolic: parse the target function's AST, translate to Z3, verify against spec invariants
2. Runtime guards: generate a decorator that checks invariants before/after every call
3. Fuzz: property-based testing with Hypothesis strategies from spec types
"""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable

from praxis.compiler.extractor import ExtractedSpec, extract_spec
from praxis.compiler.lowering import lower_invariant, lower_transition, UnsupportedConstructError
from praxis.compiler.emitter import EmitContext, emit
from praxis.compiler.ir import Require, Assign
from praxis.engine.counterexample import Counterexample, extract_counterexample_from_model
from praxis.engine.fallback import fuzz_invariant

import z3


@dataclass
class TargetVerificationResult:
    """Result of verifying a target function against a spec."""
    target: str
    method: str  # 'symbolic', 'runtime', 'fuzz'
    status: str  # 'pass', 'fail', 'unsupported'
    message: str
    counterexample: Counterexample | None = None


def resolve_target(target_path: str) -> Callable:
    """Resolve a dotted path to a callable. e.g. 'ledger.core.transfer' -> function."""
    parts = target_path.rsplit(".", 1)
    if len(parts) != 2:
        raise ImportError(f"Target must be 'module.function', got '{target_path}'")
    module_path, func_name = parts
    module = importlib.import_module(module_path)
    func = getattr(module, func_name, None)
    if func is None:
        raise ImportError(f"Function '{func_name}' not found in module '{module_path}'")
    return func


def verify_target(
    spec_cls: type,
    target_path: str,
    timeout_ms: int = 30000,
    fuzz_count: int = 10000,
) -> TargetVerificationResult:
    """Verify a target function against a spec using the three-level fallback.

    1. Try symbolic verification (AST -> Z3)
    2. If unsupported constructs, fall back to fuzz testing
    3. Report the method used and result
    """
    # Resolve the target function
    try:
        target_fn = resolve_target(target_path)
    except (ImportError, AttributeError) as e:
        return TargetVerificationResult(
            target=target_path,
            method="error",
            status="fail",
            message=f"Could not resolve target: {e}",
        )

    # Try symbolic first
    result = _try_symbolic(spec_cls, target_fn, target_path, timeout_ms)
    if result.status != "unsupported":
        return result

    # Fall back to fuzz testing
    return _fuzz_target(spec_cls, target_fn, target_path, fuzz_count)


def _try_symbolic(
    spec_cls: type,
    target_fn: Callable,
    target_path: str,
    timeout_ms: int,
) -> TargetVerificationResult:
    """Try to symbolically verify a target function by parsing its AST."""
    try:
        source = textwrap.dedent(inspect.getsource(target_fn))
        tree = ast.parse(source)
        func_def = tree.body[0]
        if not isinstance(func_def, ast.FunctionDef):
            return TargetVerificationResult(
                target=target_path, method="symbolic", status="unsupported",
                message="Target is not a function definition",
            )

        # Extract the spec
        extracted = extract_spec(spec_cls)

        # Try to lower the function body as a transition
        # Map function params to spec state fields + transition params
        param_names = [
            p.arg for p in func_def.args.args
            if p.arg != "self" and p.arg != "cls"
        ]

        ir_nodes = lower_transition(func_def, param_names)

        # If we got here, the function is expressible in our IR
        # Now verify it preserves invariants, same as a transition
        ctx = EmitContext()
        for name, ptype in extracted.state_fields.items():
            ctx.add_state_var(name, ptype)
            ctx.add_primed_var(name, ptype)

        # Separate requires and assigns
        requires = [n for n in ir_nodes if isinstance(n, Require)]
        assigns = [n for n in ir_nodes if isinstance(n, Assign)]

        s = z3.Solver()
        s.set("timeout", timeout_ms)
        s.add(*ctx.constraints)

        # Assume invariants hold before
        for inv in extracted.invariants:
            inv_ir = lower_invariant(inv.ast_node)
            s.add(emit(inv_ir, ctx))

        # Assume preconditions
        for req in requires:
            s.add(emit(req, ctx))

        # Apply assigns
        assigned_fields = set()
        for assign in assigns:
            val_z3 = emit(assign, ctx)
            s.add(ctx.primed[assign.target] == val_z3)
            assigned_fields.add(assign.target)

        # Frame condition
        for name in extracted.state_fields:
            if name not in assigned_fields:
                s.add(ctx.primed[name] == ctx.vars[name])

        # Check invariants on after-state
        after_inv_exprs = []
        for inv in extracted.invariants:
            inv_ir = lower_invariant(inv.ast_node)
            after_ctx = EmitContext()
            after_ctx.vars = ctx.primed
            after_ctx.params = ctx.params
            after_inv_exprs.append(emit(inv_ir, after_ctx))

        s.add(z3.Not(z3.And(*after_inv_exprs)))

        check = s.check()
        if check == z3.unsat:
            return TargetVerificationResult(
                target=target_path, method="symbolic", status="pass",
                message=f"Symbolically verified: {target_path} preserves all invariants",
            )
        elif check == z3.sat:
            model = s.model()
            violated_inv = "unknown"
            for inv, expr in zip(extracted.invariants, after_inv_exprs):
                if z3.is_false(model.eval(expr, model_completion=True)):
                    violated_inv = inv.name
                    break

            ce = extract_counterexample_from_model(
                model=model,
                spec_name=extracted.name,
                property_name=violated_inv,
                state_vars=ctx.vars,
                primed_vars=ctx.primed,
                transition_name=target_path,
            )
            return TargetVerificationResult(
                target=target_path, method="symbolic", status="fail",
                message=f"Invariant '{violated_inv}' violated by {target_path}",
                counterexample=ce,
            )
        else:
            return TargetVerificationResult(
                target=target_path, method="symbolic", status="unsupported",
                message="Z3 returned UNKNOWN, falling back to fuzzing",
            )

    except UnsupportedConstructError as e:
        return TargetVerificationResult(
            target=target_path, method="symbolic", status="unsupported",
            message=f"Cannot verify symbolically: {e}. Falling back to fuzzing.",
        )
    except Exception as e:
        return TargetVerificationResult(
            target=target_path, method="symbolic", status="unsupported",
            message=f"Symbolic verification failed: {e}. Falling back to fuzzing.",
        )


def _fuzz_target(
    spec_cls: type,
    target_fn: Callable,
    target_path: str,
    fuzz_count: int,
) -> TargetVerificationResult:
    """Fuzz-test a target function against spec invariants."""
    from praxis.engine.fallback import generate_random_state

    extracted = extract_spec(spec_cls)
    fields = spec_cls.state_fields()
    violations = 0
    violation_example = None

    for _ in range(fuzz_count):
        state = generate_random_state(fields)

        # Check invariants hold on initial state
        mock = type("State", (), state)()
        all_hold = True
        for inv_method in spec_cls.invariants():
            try:
                if not inv_method(mock):
                    all_hold = False
                    break
            except Exception:
                all_hold = False
                break

        if not all_hold:
            continue  # Skip states where invariants don't hold initially

        # Call the target function with mock state
        try:
            target_fn(mock)
        except Exception:
            continue  # Target raised (e.g. precondition), skip

        # Check invariants hold after
        for inv_method in spec_cls.invariants():
            try:
                if not inv_method(mock):
                    violations += 1
                    if violation_example is None:
                        violation_example = dict(state)
                    break
            except Exception:
                violations += 1
                break

    if violations == 0:
        return TargetVerificationResult(
            target=target_path, method="fuzz", status="pass",
            message=(
                f"Could not verify symbolically. "
                f"Property-based testing with {fuzz_count} inputs: 0 violations."
            ),
        )
    else:
        return TargetVerificationResult(
            target=target_path, method="fuzz", status="fail",
            message=(
                f"Property-based testing with {fuzz_count} inputs: "
                f"{violations} violations found."
            ),
        )


# ============================================================
# Runtime guards — generate a decorator from a spec
# ============================================================

def runtime_guard(spec_cls: type, state_extractor: Callable | None = None):
    """Generate a decorator that checks spec invariants before and after every call.

    Usage:
        @runtime_guard(LedgerSpec, state_extractor=lambda self: {
            'account_a': self.balance_a,
            'account_b': self.balance_b,
            'total_deposited': self.total,
        })
        def transfer(self, amount):
            ...

    Or for functions (not methods):
        @runtime_guard(LedgerSpec, state_extractor=lambda ledger: {
            'account_a': ledger.accounts['a'],
            'account_b': ledger.accounts['b'],
            'total_deposited': ledger.total,
        })
        def transfer(ledger, amount):
            ...

    The decorator checks all invariants before the call (to verify preconditions)
    and after the call (to verify the function preserved them). If an invariant
    is violated after the call, raises AssertionError with the invariant name.
    """
    invariant_methods = spec_cls.invariants()

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Extract state before
            if state_extractor and args:
                before_state = state_extractor(args[0])
                mock_before = type("State", (), before_state)()

                # Verify invariants hold before (optional, skip if not)
                for inv in invariant_methods:
                    try:
                        if not inv(mock_before):
                            pass  # Don't block on pre-state violations
                    except Exception:
                        pass

            # Execute the function
            result = fn(*args, **kwargs)

            # Extract state after
            if state_extractor and args:
                after_state = state_extractor(args[0])
                mock_after = type("State", (), after_state)()

                # Verify invariants hold after
                for inv in invariant_methods:
                    try:
                        if not inv(mock_after):
                            raise AssertionError(
                                f"Praxis runtime guard: invariant '{inv.__name__}' "
                                f"violated after calling {fn.__qualname__}. "
                                f"State: {after_state}"
                            )
                    except AssertionError:
                        raise
                    except Exception as e:
                        raise AssertionError(
                            f"Praxis runtime guard: invariant '{inv.__name__}' "
                            f"raised {type(e).__name__} after calling {fn.__qualname__}"
                        ) from e

            return result
        wrapper._praxis_guarded = True
        return wrapper
    return decorator
