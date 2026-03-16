"""Praxis benchmark suite — measures verification performance."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt, BoundedFloat
from praxis.decorators import require
from praxis.engine.verifier import verify_spec
from praxis.compiler.extractor import extract_spec
from praxis.compiler.lowering import lower_invariant
from praxis.compiler.emitter import EmitContext, emit


# ============================================================
# Benchmark specs
# ============================================================

class GPUSchedulerSpec(Spec):
    vram_total: BoundedInt[1, 640]
    vram_used: BoundedInt[0, 640]
    job_count: BoundedInt[0, 100]
    budget: BoundedFloat[0.0, 10000.0]
    cost: BoundedFloat[0.0, 10000.0]

    @invariant
    def no_overcommit(self):
        return self.vram_used <= self.vram_total

    @invariant
    def non_negative(self):
        return And(self.vram_used >= 0, self.job_count >= 0)

    @invariant
    def budget_ok(self):
        return self.cost <= self.budget

    @transition
    def schedule(self, vram: BoundedInt[1, 80], c: BoundedFloat[0.0, 100.0]):
        require(self.vram_used + vram <= self.vram_total)
        require(self.cost + c <= self.budget)
        self.vram_used += vram
        self.cost += c
        self.job_count += 1

    @transition
    def release(self, vram: BoundedInt[1, 80], c: BoundedFloat[0.0, 100.0]):
        require(self.job_count > 0)
        require(self.vram_used >= vram)
        require(self.cost >= c)
        self.vram_used -= vram
        self.cost -= c
        self.job_count -= 1


def _make_wide_spec(n_fields: int, n_invariants: int, n_transitions: int) -> type:
    """Dynamically create a spec with many fields/invariants/transitions."""
    annotations = {}
    for i in range(n_fields):
        annotations[f"f{i}"] = BoundedInt[0, 100]

    methods = {}
    for i in range(n_invariants):
        field = f"f{i % n_fields}"
        def make_inv(f):
            @invariant
            def inv(self):
                return getattr(self, f) >= 0
            inv.__name__ = f"inv_{f}"
            inv.__qualname__ = f"WideSpec.inv_{f}"
            return inv
        methods[f"inv_{field}_{i}"] = make_inv(field)

    for i in range(n_transitions):
        field = f"f{i % n_fields}"
        def make_trans(f):
            @transition
            def trans(self, v: BoundedInt[1, 10]):
                require(getattr(self, f) + v <= 100)
                setattr(self, f, getattr(self, f) + v)
            trans.__name__ = f"trans_{f}"
            trans.__qualname__ = f"WideSpec.trans_{f}"
            return trans
        methods[f"trans_{field}_{i}"] = make_trans(field)

    ns = {"__annotations__": annotations, **methods}
    return type("WideSpec", (Spec,), ns)


# ============================================================
# Benchmark runner
# ============================================================

def bench(name: str, fn, iterations: int = 3) -> dict:
    """Run a benchmark and return timing results."""
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    avg = sum(times) / len(times)
    best = min(times)
    return {
        "name": name,
        "avg_ms": round(avg * 1000, 1),
        "best_ms": round(best * 1000, 1),
        "iterations": iterations,
    }


def bench_gpu_scheduler() -> dict:
    return bench("GPU Scheduler (5 fields, 3 inv, 2 trans)", lambda: verify_spec(GPUSchedulerSpec))


def bench_wide_10() -> dict:
    spec = _make_wide_spec(10, 10, 5)
    return bench("Wide Spec (10 fields, 10 inv, 5 trans)", lambda: verify_spec(spec))


def bench_wide_20_inv() -> dict:
    spec = _make_wide_spec(5, 20, 3)
    return bench("20-Invariant Spec (5 fields, 20 inv, 3 trans)", lambda: verify_spec(spec))


def bench_extraction() -> dict:
    def fn():
        extract_spec(GPUSchedulerSpec)
    return bench("AST Extraction (GPU Scheduler)", fn, iterations=100)


def bench_lowering() -> dict:
    extracted = extract_spec(GPUSchedulerSpec)
    def fn():
        for inv in extracted.invariants:
            lower_invariant(inv.ast_node)
    return bench("Lowering (GPU Scheduler invariants)", fn, iterations=100)


def main() -> None:
    print("Praxis Benchmark Suite")
    print("=" * 60)
    print()

    results = []
    benchmarks = [
        bench_gpu_scheduler,
        bench_wide_10,
        bench_wide_20_inv,
        bench_extraction,
        bench_lowering,
    ]

    for b in benchmarks:
        r = b()
        results.append(r)
        print(f"  {r['name']:<50} {r['avg_ms']:>8.1f}ms avg  {r['best_ms']:>8.1f}ms best")

    print()
    print("=" * 60)

    # Save results
    output_path = Path(__file__).parent / "results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
