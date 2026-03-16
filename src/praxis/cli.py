"""Praxis CLI — check, explain, init commands."""

from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import sys
from pathlib import Path
from typing import Any

from praxis.spec import Spec
from praxis.engine.verifier import verify_spec
from praxis.engine.target_verifier import TargetVerificationResult, verify_target


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="praxis",
        description="Formal verification disguised as a test framework",
    )
    subparsers = parser.add_subparsers(dest="command")

    check_parser = subparsers.add_parser("check", help="Verify specs in file/directory")
    check_parser.add_argument("path", help="File or directory to check")
    check_parser.add_argument("--format", choices=["human", "json"], default="human")
    check_parser.add_argument("--timeout", type=int, default=30, help="Per-property timeout in seconds")
    check_parser.add_argument("--fuzz", type=int, default=10000, help="Fuzz iteration count for fallback")

    verify_parser = subparsers.add_parser("verify", help="Verify a target function against a spec")
    verify_parser.add_argument("spec_path", help="Spec file containing the spec class(es)")
    verify_parser.add_argument("--target", required=True, help="Dotted path to the target function (e.g. myapp.payments.transfer)")
    verify_parser.add_argument("--format", choices=["human", "json"], default="human")
    verify_parser.add_argument("--timeout", type=int, default=30, help="Per-property timeout in seconds")
    verify_parser.add_argument("--fuzz", type=int, default=10000, help="Fuzz iteration count for fallback")

    explain_parser = subparsers.add_parser("explain", help="Explain a spec in plain English")
    explain_parser.add_argument("path", help="Spec file to explain")
    explain_parser.add_argument("--format", choices=["human", "json"], default="human")

    init_parser = subparsers.add_parser("init", help="Generate a starter spec")
    init_parser.add_argument("name", help="Name for the spec (e.g., user_service)")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(2)

    if args.command == "check":
        sys.exit(_run_check(args))
    elif args.command == "verify":
        sys.exit(_run_verify(args))
    elif args.command == "explain":
        sys.exit(_run_explain(args))
    elif args.command == "init":
        sys.exit(_run_init(args))


def _run_check(args: argparse.Namespace) -> int:
    """Run verification checks. Returns exit code: 0=pass, 1=fail, 2=error."""
    path = Path(args.path)
    timeout_ms = args.timeout * 1000

    spec_files = _find_spec_files(path)
    if not spec_files:
        if args.format == "json":
            print(json.dumps({"error": f"No spec files found in {path}"}))
        else:
            print(f"No spec files found in {path}")
        return 2

    all_results = []
    has_failure = False
    has_error = False

    for spec_file in spec_files:
        spec_classes = _load_spec_classes(spec_file)
        for spec_cls in spec_classes:
            result = verify_spec(spec_cls, timeout_ms=timeout_ms, fuzz_count=args.fuzz)
            all_results.append(result)
            for r in result.results:
                if r.status == "fail":
                    has_failure = True
                elif r.status == "error":
                    has_error = True

    if args.format == "json":
        _print_json(all_results)
    else:
        _print_human(all_results)

    if has_failure:
        return 1
    if has_error:
        return 2
    return 0


def _run_verify(args: argparse.Namespace) -> int:
    """Verify a target function against spec(s). Returns exit code: 0=pass, 1=fail, 2=error."""
    spec_path = Path(args.spec_path)
    target_path = args.target
    timeout_ms = args.timeout * 1000

    spec_classes = _load_spec_classes(spec_path)
    if not spec_classes:
        if args.format == "json":
            print(json.dumps({"error": f"No spec classes found in {spec_path}"}))
        else:
            print(f"No spec classes found in {spec_path}")
        return 2

    results: list[TargetVerificationResult] = []
    has_failure = False
    has_error = False

    for spec_cls in spec_classes:
        result = verify_target(spec_cls, target_path, timeout_ms=timeout_ms, fuzz_count=args.fuzz)
        results.append(result)
        if result.status == "fail":
            has_failure = True
        elif result.status == "unsupported" or result.method == "error":
            has_error = True

    if args.format == "json":
        _print_verify_json(results)
    else:
        _print_verify_human(results)

    if has_failure:
        return 1
    if has_error:
        return 2
    return 0


def _print_verify_human(results: list) -> None:
    """Print human-readable target verification results."""
    for r in results:
        status_symbol = {"pass": "PASSED", "fail": "FAILED"}.get(r.status, r.status.upper())
        print(f"\n{'='*60}")
        print(f"Target: {r.target}")
        print(f"Method: {r.method}")
        print(f"Status: {status_symbol}")
        print(f"{'='*60}")
        print(f"  {r.message}")
        if r.counterexample:
            print()
            for line in r.counterexample.to_human().split("\n"):
                print(f"    {line}")


def _print_verify_json(results: list) -> None:
    """Print JSON target verification results."""
    output = []
    for r in results:
        item = {
            "target": r.target,
            "method": r.method,
            "status": r.status,
            "message": r.message,
        }
        if r.counterexample:
            item["counterexample"] = r.counterexample.to_json()
        output.append(item)
    print(json.dumps(output, indent=2))


def _run_explain(args: argparse.Namespace) -> int:
    """Explain a spec in plain English (or JSON)."""
    path = Path(args.path)
    spec_files = _find_spec_files(path)
    if not spec_files:
        if args.format == "json":
            print(json.dumps({"error": f"No spec files found in {path}"}))
        else:
            print(f"No spec files found in {path}")
        return 2

    all_explanations = []
    for spec_file in spec_files:
        spec_classes = _load_spec_classes(spec_file)
        for spec_cls in spec_classes:
            if args.format == "json":
                all_explanations.append(_explain_spec_json(spec_cls))
            else:
                _explain_spec(spec_cls)

    if args.format == "json":
        print(json.dumps(all_explanations, indent=2))
    return 0


def _explain_spec(spec_cls: type) -> None:
    """Print a human-readable explanation of a spec."""
    print(f"\n{spec_cls.__name__}:")
    if spec_cls.__doc__:
        print(f"  {spec_cls.__doc__.strip()}")
    print()

    # State fields
    fields = spec_cls.state_fields()
    if fields:
        print("  State:")
        for name, ptype in fields.items():
            pt = getattr(ptype, "_praxis_type", "unknown")
            if pt in ("BoundedInt", "BoundedFloat"):
                print(f"    - {name}: {pt.lower().replace('bounded', '')} in [{ptype._lo}, {ptype._hi}]")
            elif pt == "Bool":
                print(f"    - {name}: boolean")
            elif pt == "Enum":
                vals = ", ".join(f"{k}={v}" for k, v in ptype._enum_values.items())
                print(f"    - {name}: enum ({vals})")
            else:
                print(f"    - {name}: {pt}")
        print()

    # Invariants
    invs = spec_cls.invariants()
    if invs:
        print("  Invariants (things that must ALWAYS be true):")
        for i, inv in enumerate(invs, 1):
            doc = (inv.__doc__ or inv.__name__).strip()
            print(f"    {i}. {inv.__name__}: {doc}")
        print()

    # Transitions
    trans = spec_cls.transitions()
    if trans:
        print("  Transitions (valid operations):")
        for i, t in enumerate(trans, 1):
            sig = inspect.signature(t)
            params = []
            for pname, p in sig.parameters.items():
                if pname == "self":
                    continue
                ann = t.__annotations__.get(pname)
                if ann and hasattr(ann, "_lo"):
                    params.append(f"{pname}: {ann._lo}-{ann._hi}")
                else:
                    params.append(pname)
            param_str = ", ".join(params)
            doc = (t.__doc__ or "").strip()
            print(f"    {i}. {t.__name__}({param_str})")
            if doc:
                print(f"       {doc}")
        print()


def _explain_spec_json(spec_cls: type) -> dict:
    """Return a JSON-serialisable explanation of a spec."""
    explanation: dict[str, Any] = {
        "name": spec_cls.__name__,
        "doc": (spec_cls.__doc__ or "").strip() or None,
    }

    # State fields
    fields = spec_cls.state_fields()
    state_info = {}
    for name, ptype in fields.items():
        pt = getattr(ptype, "_praxis_type", "unknown")
        if pt in ("BoundedInt", "BoundedFloat"):
            state_info[name] = {"type": pt.lower().replace("bounded", ""), "lo": ptype._lo, "hi": ptype._hi}
        elif pt == "Bool":
            state_info[name] = {"type": "boolean"}
        elif pt == "Enum":
            state_info[name] = {"type": "enum", "values": {k: v for k, v in ptype._enum_values.items()}}
        else:
            state_info[name] = {"type": pt}
    explanation["state"] = state_info

    # Invariants
    invs = spec_cls.invariants()
    explanation["invariants"] = [
        {"name": inv.__name__, "doc": (inv.__doc__ or inv.__name__).strip()}
        for inv in invs
    ]

    # Transitions
    trans = spec_cls.transitions()
    transition_info = []
    for t in trans:
        sig = inspect.signature(t)
        params = {}
        for pname, p in sig.parameters.items():
            if pname == "self":
                continue
            ann = t.__annotations__.get(pname)
            if ann and hasattr(ann, "_lo"):
                params[pname] = {"lo": ann._lo, "hi": ann._hi}
            else:
                params[pname] = {}
        transition_info.append({
            "name": t.__name__,
            "doc": (t.__doc__ or "").strip() or None,
            "params": params,
        })
    explanation["transitions"] = transition_info

    return explanation


def _run_init(args: argparse.Namespace) -> int:
    """Generate a starter spec file."""
    name = args.name
    filename = f"spec_{name}.py"
    class_name = "".join(w.capitalize() for w in name.split("_")) + "Spec"

    content = f'''"""Spec for {name.replace('_', ' ')}."""

from praxis import Spec, invariant, transition
from praxis.types import BoundedInt
from praxis.decorators import require


class {class_name}(Spec):
    """{name.replace('_', ' ').title()} specification."""

    value: BoundedInt[0, 1000]
    count: BoundedInt[0, 100]

    @invariant
    def value_non_negative(self):
        """Value is always non-negative."""
        return self.value >= 0

    @invariant
    def count_non_negative(self):
        """Count is always non-negative."""
        return self.count >= 0

    @transition
    def increment(self, amount: BoundedInt[1, 100]):
        """Increase value by amount."""
        require(self.value + amount <= 1000)
        self.value += amount
        self.count += 1

    @transition
    def decrement(self, amount: BoundedInt[1, 100]):
        """Decrease value by amount."""
        require(self.value >= amount)
        require(self.count > 0)
        self.value -= amount
        self.count -= 1
'''

    filepath = Path(filename)
    if filepath.exists():
        print(f"File {filename} already exists")
        return 1

    filepath.write_text(content)
    print(f"Created {filename}")
    print(f"\nRun: pytest {filename} -v")
    print(f"  or: praxis check {filename}")
    return 0


def _find_spec_files(path: Path) -> list[Path]:
    """Find spec files (spec_*.py or *_spec.py)."""
    if path.is_file():
        return [path]
    if path.is_dir():
        files = []
        for f in sorted(path.rglob("*.py")):
            if f.stem.startswith("spec_") or f.stem.endswith("_spec"):
                files.append(f)
        return files
    return []


def _load_spec_classes(filepath: Path) -> list[type]:
    """Load Spec subclasses from a Python file."""
    spec = importlib.util.spec_from_file_location(filepath.stem, filepath)
    if spec is None or spec.loader is None:
        return []
    module = importlib.util.module_from_spec(spec)
    sys.modules[filepath.stem] = module
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        print(f"Error loading {filepath}: {e}", file=sys.stderr)
        return []

    classes = []
    for name in dir(module):
        obj = getattr(module, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, Spec)
            and obj is not Spec
            and not name.startswith("_")
        ):
            classes.append(obj)
    return classes


def _print_human(results: list) -> None:
    """Print human-readable verification results."""
    for spec_result in results:
        print(f"\n{'='*60}")
        print(f"Spec: {spec_result.spec_name}")
        print(f"{'='*60}")
        for r in spec_result.results:
            status_symbol = {"pass": "PASSED", "fail": "FAILED", "timeout": "TIMEOUT", "error": "ERROR"}
            symbol = status_symbol.get(r.status, r.status.upper())
            kind = r.kind
            name = r.transition_name or r.property_name
            print(f"  {kind}_{name} {symbol}")
            if r.status == "fail" and r.counterexample:
                for line in r.counterexample.to_human().split("\n"):
                    print(f"    {line}")
            if r.status == "error" and r.error_message:
                print(f"    Error: {r.error_message}")
        print(f"\n  {spec_result.pass_count} passed, {spec_result.fail_count} failed")


def _print_json(results: list) -> None:
    """Print JSON verification results."""
    output = []
    for spec_result in results:
        spec_data = {
            "spec": spec_result.spec_name,
            "passed": spec_result.passed,
            "results": [],
        }
        for r in spec_result.results:
            item = {
                "property": r.property_name,
                "kind": r.kind,
                "status": r.status,
            }
            if r.transition_name:
                item["transition"] = r.transition_name
            if r.counterexample:
                item["counterexample"] = r.counterexample.to_json()
            if r.error_message:
                item["error"] = r.error_message
            spec_data["results"].append(item)
        output.append(spec_data)
    print(json.dumps(output, indent=2))
