"""Praxis pytest plugin — auto-discovers and runs spec verification."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from praxis.spec import Spec
from praxis.engine.verifier import verify_spec


def pytest_sessionstart(session):
    """Clear verification cache at the start of each test session."""
    PraxisItem._result_cache.clear()


def pytest_addoption(parser):
    """Add praxis-specific command line options."""
    group = parser.getgroup("praxis", "Praxis formal verification")
    group.addoption(
        "--praxis-timeout",
        type=int,
        default=30000,
        help="Z3 timeout per property in milliseconds (default: 30000)",
    )
    group.addoption(
        "--praxis-fuzz-count",
        type=int,
        default=10000,
        help="Number of fuzz iterations for fallback (default: 10000)",
    )


def pytest_collect_file(parent, file_path):
    """Collect spec_*.py and *_spec.py files."""
    if file_path.suffix == ".py":
        if file_path.stem.startswith("spec_") or file_path.stem.endswith("_spec"):
            return PraxisFile.from_parent(parent, path=file_path)
    return None


class PraxisFile(pytest.File):
    """A file containing Praxis spec classes."""

    def collect(self):
        # Import the module
        spec = importlib.util.spec_from_file_location(
            self.path.stem, self.path
        )
        if spec is None or spec.loader is None:
            return
        module = importlib.util.module_from_spec(spec)
        sys.modules[self.path.stem] = module
        spec.loader.exec_module(module)

        # Find Spec subclasses
        for name in dir(module):
            obj = getattr(module, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, Spec)
                and obj is not Spec
                and not name.startswith("_")
            ):
                # Yield items per @initial predicate
                for init in obj.initials():
                    yield PraxisItem.from_parent(
                        self,
                        name=f"{name}::initial_{init.__name__}",
                        spec_cls=obj,
                        check_kind="initial",
                        check_name=init.__name__,
                    )
                # Yield items per invariant
                for inv in obj.invariants():
                    yield PraxisItem.from_parent(
                        self,
                        name=f"{name}::invariant_{inv.__name__}",
                        spec_cls=obj,
                        check_kind="invariant",
                        check_name=inv.__name__,
                    )
                # Yield items per transition
                for trans in obj.transitions():
                    yield PraxisItem.from_parent(
                        self,
                        name=f"{name}::transition_{trans.__name__}",
                        spec_cls=obj,
                        check_kind="transition",
                        check_name=trans.__name__,
                    )
                # Yield items per @verify target
                for ver in obj.verifications():
                    yield PraxisItem.from_parent(
                        self,
                        name=f"{name}::verify_{ver.__name__}",
                        spec_cls=obj,
                        check_kind="verify",
                        check_name=ver.__name__,
                    )


class PraxisItem(pytest.Item):
    """A single verification check (invariant or transition)."""

    def __init__(self, name, parent, spec_cls, check_kind, check_name):
        super().__init__(name, parent)
        self.spec_cls = spec_cls
        self.check_kind = check_kind
        self.check_name = check_name

    # Class-level cache: verify each spec class only once per test session
    _result_cache: dict[type, object] = {}

    def runtest(self):
        timeout = self.config.getoption("praxis_timeout", 30000)
        fuzz_count = self.config.getoption("praxis_fuzz_count", 10000)

        if self.spec_cls not in PraxisItem._result_cache:
            PraxisItem._result_cache[self.spec_cls] = verify_spec(
                self.spec_cls, timeout_ms=timeout, fuzz_count=fuzz_count
            )
        result = PraxisItem._result_cache[self.spec_cls]

        # Find our specific check
        for r in result.results:
            name_match = (
                (self.check_kind == "initial" and r.kind == "initial" and r.property_name == self.check_name)
                or (self.check_kind == "invariant" and r.kind == "invariant" and r.property_name == self.check_name)
                or (self.check_kind == "transition" and r.kind == "transition" and r.transition_name == self.check_name)
                or (self.check_kind == "verify" and r.kind == "verify" and r.property_name == self.check_name)
            )
            if name_match:
                if r.status == "fail":
                    raise PraxisFailure(r)
                elif r.status == "error":
                    raise PraxisError(r)
                elif r.status == "timeout":
                    pytest.skip(f"Z3 timeout on {self.check_name}")
                return
        # If we didn't find a matching result, that's an error
        raise PraxisError(None)

    def repr_failure(self, excinfo):
        if isinstance(excinfo.value, PraxisFailure):
            r = excinfo.value.result
            if r.counterexample:
                return _format_counterexample_box(r)
            return f"Verification failed: {r.property_name}"
        if isinstance(excinfo.value, PraxisError):
            r = excinfo.value.result
            if r and r.error_message:
                return f"Verification error: {r.error_message}"
            return "Verification error"
        return str(excinfo.value)

    def reportinfo(self):
        return self.path, None, f"praxis::{self.name}"


def _format_counterexample_box(result) -> str:
    """Format a counterexample with Unicode box-drawing for pytest output."""
    ce = result.counterexample
    lines = []

    # Header
    lines.append(f"Invariant violated: {ce.property_name}")
    if ce.message:
        lines.append(f'  "{ce.message}"')
    lines.append("")

    def box(title: str, items: dict[str, object]) -> list[str]:
        if not items:
            return []
        width = max(len(f"{k} = {v}") for k, v in items.items()) + 4
        width = max(width, len(title) + 4)
        out = []
        out.append(f"\u250c\u2500 {title} " + "\u2500" * (width - len(title) - 3) + "\u2510")
        for k, v in sorted(items.items()):
            content = f"{k} = {v}"
            out.append(f"\u2502 {content:<{width - 2}} \u2502")
        out.append("\u2514" + "\u2500" * (width) + "\u2518")
        return out

    if ce.before:
        lines.extend(box("Before", ce.before))
    if ce.inputs:
        lines.extend(box("Input", ce.inputs))
    if ce.after:
        lines.extend(box("After", ce.after))

    return "\n".join(lines)


class PraxisFailure(Exception):
    """Raised when a Praxis verification check fails."""
    def __init__(self, result):
        self.result = result
        super().__init__(str(result))


class PraxisError(Exception):
    """Raised when a Praxis verification check errors."""
    def __init__(self, result):
        self.result = result
        super().__init__(str(result))
