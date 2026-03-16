"""Bridge APIs — connect specs to implementations without coupling.

Three ways to use a spec against real code:

1. praxis.fuzz() — run in tests, fuzz the implementation against the spec
2. praxis.monitor() — attach at startup, log or raise on violations at runtime
3. @runtime_guard — decorator on individual methods (legacy, more coupled)

The implementation never imports praxis. The spec lives in specs/.
The connection lives in tests or config.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger("praxis.bridge")


@dataclass
class FuzzResult:
    """Result of fuzz-testing an implementation against a spec."""
    spec_name: str
    target_name: str
    iterations: int
    violations: int
    first_violation: dict[str, Any] | None = None
    invariant_violated: str | None = None

    @property
    def passed(self) -> bool:
        return self.violations == 0

    def __repr__(self) -> str:
        if self.passed:
            return f"FuzzResult(PASS, {self.iterations} iterations, 0 violations)"
        return (
            f"FuzzResult(FAIL, {self.violations}/{self.iterations} violations, "
            f"invariant='{self.invariant_violated}', state={self.first_violation})"
        )


def fuzz(
    implementation: object,
    spec_cls: type,
    state_extractor: Callable[[object], dict[str, Any]],
    operations: list[Callable[[object], None]] | None = None,
    iterations: int = 10000,
    seed: int | None = None,
) -> FuzzResult:
    """Fuzz-test an implementation against a spec's invariants.

    Runs random sequences of operations on the implementation,
    checking spec invariants after each operation.

    Args:
        implementation: The live object to test.
        spec_cls: The Spec class defining invariants.
        state_extractor: Maps implementation state to spec state dict.
        operations: List of callables that mutate the implementation.
            Each is called with the implementation as the argument.
            If None, checks invariants on the current state only.
        iterations: Number of random operations to run.
        seed: Random seed for reproducibility.

    Returns:
        FuzzResult with pass/fail and violation details.

    Example:
        def test_credit_invariants():
            service = CreditService()
            service.create_user("alice")
            service.add_credits("alice", 1000)

            result = praxis.fuzz(
                service,
                CreditServiceSpec,
                state_extractor=lambda s: {
                    'balance': s.get_balance("alice"),
                    'total_spent': s.get_total_spent("alice"),
                    'total_added': s.get_total_added("alice"),
                },
                operations=[
                    lambda s: s.purchase("alice", random.randint(1, 100)),
                    lambda s: s.add_credits("alice", random.randint(1, 50)),
                    lambda s: s.refund("alice", random.randint(1, 20)),
                ],
            )
            assert result.passed, result
    """
    if seed is not None:
        random.seed(seed)

    # Validate state_extractor returns correct fields
    try:
        sample = state_extractor(implementation)
        spec_fields = set(spec_cls.state_fields().keys())
        extracted_fields = set(sample.keys())
        if extracted_fields != spec_fields:
            missing = spec_fields - extracted_fields
            extra = extracted_fields - spec_fields
            raise ValueError(
                f"state_extractor field mismatch: "
                f"missing={missing or 'none'}, extra={extra or 'none'}. "
                f"Expected fields: {spec_fields}"
            )
    except ValueError:
        raise
    except Exception:
        pass  # Can't validate yet (implementation not ready)

    invariant_methods = spec_cls.invariants()
    violations = 0
    first_violation = None
    violated_inv = None

    for i in range(iterations):
        # Run a random operation if provided
        if operations:
            op = random.choice(operations)
            try:
                op(implementation)
            except Exception:
                continue  # Operation raised (e.g., insufficient funds) — skip

        # Extract state and check invariants
        try:
            state = state_extractor(implementation)
        except Exception:
            continue

        mock = type("State", (), state)()
        for inv in invariant_methods:
            try:
                if not inv(mock):
                    violations += 1
                    if first_violation is None:
                        first_violation = dict(state)
                        violated_inv = inv.__name__
                    break
            except Exception:
                violations += 1
                if first_violation is None:
                    first_violation = dict(state)
                    violated_inv = inv.__name__
                break

    return FuzzResult(
        spec_name=spec_cls.__name__,
        target_name=type(implementation).__name__,
        iterations=iterations,
        violations=violations,
        first_violation=first_violation,
        invariant_violated=violated_inv,
    )


def monitor(
    cls: type,
    spec_cls: type,
    state_extractor: Callable[[object], dict[str, Any]],
    methods: list[str] | None = None,
    mode: str = "log",
) -> None:
    """Attach spec monitoring to a class at config time.

    Wraps specified methods (or all public methods) to check spec
    invariants after each call. No decorator needed on the class itself.

    Args:
        cls: The implementation class to monitor.
        spec_cls: The Spec class defining invariants.
        state_extractor: Maps implementation state to spec state dict.
        methods: List of method names to monitor. If None, monitors
            all public methods (not starting with '_').
        mode: "log" (default) — log violations without raising.
              "enforce" — raise AssertionError on violation.
              "off" — disable monitoring (no-op).

    Example:
        # In app startup or conftest.py — one line
        praxis.monitor(
            CreditService,
            CreditServiceSpec,
            state_extractor=lambda self: {
                'balance': self.balance,
                'total_spent': self.total_spent,
                'total_added': self.total_added,
            },
            methods=["purchase", "add_credits", "refund"],
        )
    """
    valid_modes = ("log", "enforce", "off")
    if mode not in valid_modes:
        raise ValueError(f"Invalid mode '{mode}'. Must be one of: {valid_modes}")

    if mode == "off":
        return

    invariant_methods = spec_cls.invariants()

    if methods is None:
        methods = [
            name for name in dir(cls)
            if not name.startswith("_") and callable(getattr(cls, name, None))
        ]

    for method_name in methods:
        original = getattr(cls, method_name, None)
        if original is None or not callable(original):
            continue
        # Guard against double-wrapping
        if getattr(original, "_praxis_monitored", False):
            continue

        @wraps(original)
        def make_wrapper(orig):
            def wrapper(self, *args, **kwargs):
                result = orig(self, *args, **kwargs)

                # Check invariants on post-state
                try:
                    state = state_extractor(self)
                    mock = type("State", (), state)()
                    for inv in invariant_methods:
                        try:
                            if not inv(mock):
                                msg = (
                                    f"Praxis monitor: invariant '{inv.__name__}' "
                                    f"violated after {cls.__name__}.{orig.__name__}(). "
                                    f"State: {state}"
                                )
                                if mode == "enforce":
                                    raise AssertionError(msg)
                                else:
                                    logger.warning(msg)
                        except AssertionError:
                            raise
                        except Exception as e:
                            logger.warning(
                                f"Praxis monitor: invariant '{inv.__name__}' "
                                f"raised {type(e).__name__} after "
                                f"{cls.__name__}.{orig.__name__}()"
                            )
                except AssertionError:
                    raise
                except Exception:
                    pass  # state_extractor failed, skip

                return result
            wrapper._praxis_monitored = True
            return wrapper

        setattr(cls, method_name, make_wrapper(original))
