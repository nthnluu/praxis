# Praxis — Technical Specification

> Formal verification disguised as a test framework.
> "pytest, but instead of example-based assertions, you write properties — and instead of running random inputs, it proves them exhaustively."

## 1. Project Identity

- **Name**: `praxis`
- **Tagline**: Formal specs humans trust. Proof loops agents run.
- **License**: MIT
- **Language**: Python 3.11+
- **Core Dependency**: Z3 Solver (`z3-solver` PyPI package)
- **Distribution**: PyPI package, pytest plugin, CLI tool

---

## 2. Problem Statement

LLM-generated code is probabilistic. System requirements are deterministic. Traditional testing (pytest, unittest) provides confidence through examples. Property-based testing (Hypothesis) provides confidence through random sampling. Neither provides **mathematical certainty**.

Praxis bridges this gap: developers write readable Python specs, and a Z3-backed engine **proves** those specs hold for ALL valid inputs — not just sampled ones.

The key insight: this is a **test tool**, not a proof assistant. It lives in `tests/`, runs in CI, and reports red/green. Developers never see Z3, TLA+, or SMT-LIB.

---

## 3. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                        Developer Surface                         │
│                                                                  │
│   from praxis import Spec, invariant, verify                  │
│   class MySpec(Spec): ...                                        │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                     Python AST extraction
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Constraint Compiler                         │
│                                                                  │
│   Phase 1: AST Parse & Extract                                   │
│     - Walk Spec subclass, extract @invariant methods             │
│     - Extract @transition methods as Hoare triples               │
│     - Extract @verify(target=fn) bindings                        │
│                                                                  │
│   Phase 2: Lower to Praxis IR                                 │
│     - Convert to SSA form with primed variables                  │
│     - Resolve type annotations to Z3 sorts                       │
│     - Build quantifier structure from forall/exists              │
│                                                                  │
│   Phase 3: Emit Z3 Assertions                                    │
│     - Generate z3.Solver() calls per invariant                   │
│     - Negate conclusion to check for counterexamples             │
│     - Bounded quantification over finite domains                 │
└────────────────────────────┬─────────────────────────────────────┘
                             │
                      Z3 solve per property
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│                      Result Reporter                             │
│                                                                  │
│   UNSAT → property holds for all inputs (GREEN)                  │
│   SAT   → counterexample found (RED + structured feedback)       │
│   UNKNOWN → solver timeout (YELLOW + fallback to fuzzing)        │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. Core API Design

### 4.1 The `Spec` Base Class

```python
from praxis import Spec, invariant, transition, verify
from praxis.types import BoundedInt, Nat, BoundedFloat

class MySpec(Spec):
    # State variables — become Z3 symbolic variables
    x: BoundedInt[0, 100]
    y: Nat  # non-negative integer, alias for BoundedInt[0, 2**31-1]

    @invariant
    def my_property(self):
        """Must always hold."""
        return self.x + self.y <= 200

    @transition
    def update_x(self, delta: BoundedInt[-10, 10]):
        """A valid state change."""
        require(self.x + delta >= 0)
        require(self.x + delta <= 100)
        self.x += delta

    @verify(target="path.to.module.my_function")
    def check_my_function(self):
        """Verify that my_function preserves all invariants."""
        pass
```

### 4.2 Type System (`praxis.types`)

All types map directly to Z3 sorts. This is the supported type vocabulary for v1:

| Praxis Type | Z3 Sort | Description |
|---|---|---|
| `BoundedInt[lo, hi]` | `z3.Int` + constraints | Integer in [lo, hi] |
| `Nat` | `z3.Int` + `>= 0` | Non-negative integer |
| `BoundedFloat[lo, hi]` | `z3.Real` + constraints | Real number in [lo, hi] |
| `Bool` | `z3.Bool` | Boolean |
| `Enum[*values]` | `z3.Int` + membership | Enumerated values |

**v1 Scope**: Only scalar types. No sets, dicts, or lists in v1. Those require array theory or uninterpreted functions and add significant complexity. Document this as a known limitation.

### 4.3 Quantifiers and Logical Operators (`praxis.logic`)

```python
from praxis.logic import forall, exists, implies, iff, And, Or, Not

# forall and exists operate over BoundedInt ranges in v1
forall(range(0, 10), lambda i: arr[i] >= 0)
exists(range(0, 10), lambda i: arr[i] == target)
implies(condition, consequence)
```

**Implementation**: `forall` over a `range(lo, hi)` unrolls to `z3.And(pred(lo), pred(lo+1), ..., pred(hi-1))` for small ranges, or uses `z3.ForAll` with bounded quantifiers for larger ones. The threshold is configurable (default: 50).

### 4.4 Invariant Verification Flow

For each `@invariant` method on a `Spec` subclass:

1. Create Z3 symbolic variables for every state field (respecting type bounds)
2. Translate the invariant body to a Z3 expression
3. Assert the **negation** of the expression
4. Call `solver.check()`
   - `UNSAT` → invariant holds for all valid states ✓
   - `SAT` → counterexample found, extract model ✗
   - `UNKNOWN` → timeout, fall back to Hypothesis fuzzing

### 4.5 Transition Verification Flow

For each `@transition` method:

1. Create "before" state variables: `x, y, ...`
2. Create "after" state variables (primed): `x', y', ...`
3. Assert all invariants hold on "before" state (assume)
4. Assert all `require()` preconditions (assume)
5. Symbolically execute the transition body to relate primed to unprimed
6. Assert **negation** of invariants on "after" state
7. `UNSAT` → transition preserves all invariants ✓

### 4.6 Target Function Verification (`@verify`)

This is the bridge to real codebases. `@verify(target=fn)` says: "prove that calling `fn` with any valid spec inputs preserves all spec invariants."

**Implementation strategy for v1**: Use a hybrid approach:

1. **Try symbolic execution first**: Parse the target function's AST, translate supported operations to Z3 expressions. If the function uses only arithmetic, comparisons, and conditionals on spec-typed variables, this works.
2. **Fall back to concolic execution**: If symbolic execution hits an unsupported construct (e.g., a library call), instrument the function with symbolic inputs and use concrete execution to explore paths.
3. **Fall back to property-based testing**: If neither works, generate Hypothesis strategies from the spec types and fuzz. Report this clearly: "Could not prove symbolically. Fuzz-tested with 10,000 inputs: 0 violations."

The fallback chain should be transparent to the user.

---

## 5. The Constraint Compiler

### 5.1 AST-to-Z3 Translation Rules

The compiler translates a restricted Python subset to Z3. Supported constructs:

| Python Construct | Z3 Translation |
|---|---|
| `self.x` (state field) | `z3.Int('x')` or `z3.Real('x')` |
| `a + b`, `a - b`, `a * b` | `z3_a + z3_b`, etc. |
| `a // b` | Custom: `z3.If(b > 0, ...)` with rounding |
| `a < b`, `a <= b`, `a == b` | `z3_a < z3_b`, etc. |
| `a and b`, `a or b`, `not a` | `z3.And(a, b)`, `z3.Or(a, b)`, `z3.Not(a)` |
| `if cond: x else: y` (ternary) | `z3.If(cond, x, y)` |
| `require(expr)` | Added as solver assertion (precondition) |
| `self.x += delta` | Primed variable: `x' = x + delta` |
| `forall(range, pred)` | Unrolled `z3.And(...)` or `z3.ForAll(...)` |

**Unsupported in v1** (must error clearly):
- Loops (`for`, `while`) — except `forall`/`exists` over bounded ranges
- Function calls to non-spec functions
- String operations
- Container mutations (dict, list, set)
- I/O of any kind
- `import` within spec methods

### 5.2 Primed Variable Convention

State mutations in `@transition` methods use the "primed variable" convention from TLA+, but hidden from the developer:

```python
# Developer writes:
@transition
def schedule_job(self, job_vram: BoundedInt[1, 80]):
    require(self.vram_used + job_vram <= self.vram_total)
    self.vram_used += job_vram

# Compiler produces:
# Before state: vram_used, vram_total
# After state: vram_used' = vram_used + job_vram
# Verify: (invariants(before) ∧ preconditions) → invariants(after)
```

### 5.3 Error Messages

**This is critical for DevEx.** Every error must be actionable.

**Counterexample format** (both human-readable and JSON):

```
INVARIANT VIOLATED: no_overcommit

  Counterexample:
    vram_total = 80
    vram_used  = 48
    job_vram   = 40

  After transition `schedule_job`:
    vram_used' = 88 > vram_total (80)

  The precondition `self.vram_used + job_vram <= self.vram_total`
  would prevent this, but it was not checked before the mutation.
```

**JSON format** (for agent consumption):

```json
{
  "status": "FAIL",
  "spec": "GPUClusterSpec",
  "property": "no_overcommit",
  "kind": "invariant_violation",
  "transition": "schedule_job",
  "counterexample": {
    "before": {"vram_total": 80, "vram_used": 48},
    "inputs": {"job_vram": 40},
    "after": {"vram_used": 88}
  },
  "explanation": "vram_used' (88) exceeds vram_total (80)"
}
```

---

## 6. pytest Integration

### 6.1 Plugin Architecture

Praxis ships as a pytest plugin. No configuration needed — `pip install praxis` registers it.

```python
# conftest.py — auto-registered by the praxis package
# (entry point: praxis.pytest_plugin)

def pytest_collect_file(parent, file_path):
    if file_path.suffix == ".py" and file_path.stem.startswith("spec_"):
        return PraxisFile.from_parent(parent, path=file_path)

class PraxisFile(pytest.File):
    def collect(self):
        # Import module, find Spec subclasses
        # Yield a PraxisItem per invariant and transition
        ...

class PraxisItem(pytest.Item):
    def runtest(self):
        # Run Z3 verification
        # On SAT (violation): raise PraxisFailure with counterexample
        ...

    def repr_failure(self, excinfo):
        # Pretty-print counterexample in pytest output
        ...
```

### 6.2 Test Discovery

Files matching `spec_*.py` or `*_spec.py` are collected. Each `Spec` subclass generates test items:
- One item per `@invariant` (standalone invariant check)
- One item per `@transition` (transition preserves all invariants)
- One item per `@verify` (target function preserves all invariants)

### 6.3 CLI

```bash
# Run via pytest (preferred)
pytest --praxis tests/spec_scheduler.py -v

# Standalone CLI (same engine, different output)
praxis check tests/spec_scheduler.py
praxis check tests/spec_scheduler.py --format json  # agent-friendly
praxis check tests/spec_scheduler.py --timeout 30   # Z3 timeout in seconds
praxis check tests/spec_scheduler.py --fuzz 10000   # fallback fuzz count
```

---

## 7. Reference Example: GPU Scheduler

This is the canonical example. All docs, tests, and tutorials should reference it.

### 7.1 The Spec

```python
# tests/spec_gpu_scheduler.py
from praxis import Spec, invariant, transition, verify
from praxis.types import BoundedInt, Nat, BoundedFloat

class GPUSchedulerSpec(Spec):
    """
    Spec for a GPU job scheduler.
    Proves that no scheduling decision ever overcommits VRAM.
    """
    # Cluster state
    vram_total: BoundedInt[1, 640]       # Total VRAM in GiB (up to 8x80GB)
    vram_used: BoundedInt[0, 640]        # Currently allocated VRAM
    job_count: BoundedInt[0, 100]        # Number of active jobs
    budget_per_hour: BoundedFloat[0.0, 10000.0]  # Hourly budget cap
    cost_per_hour: BoundedFloat[0.0, 10000.0]    # Current hourly spend

    # --- Invariants ---

    @invariant
    def no_overcommit(self):
        """VRAM usage never exceeds capacity."""
        return self.vram_used <= self.vram_total

    @invariant
    def non_negative_resources(self):
        """Resources are never negative."""
        return And(self.vram_used >= 0, self.job_count >= 0)

    @invariant
    def budget_respected(self):
        """Hourly spend never exceeds budget."""
        return self.cost_per_hour <= self.budget_per_hour

    # --- Transitions ---

    @transition
    def schedule_job(self, job_vram: BoundedInt[1, 80], job_cost: BoundedFloat[0.0, 100.0]):
        """Assign a job to the cluster."""
        require(self.vram_used + job_vram <= self.vram_total)
        require(self.cost_per_hour + job_cost <= self.budget_per_hour)
        self.vram_used += job_vram
        self.cost_per_hour += job_cost
        self.job_count += 1

    @transition
    def release_job(self, job_vram: BoundedInt[1, 80], job_cost: BoundedFloat[0.0, 100.0]):
        """Release a job from the cluster."""
        require(self.job_count > 0)
        require(self.vram_used >= job_vram)
        require(self.cost_per_hour >= job_cost)
        self.vram_used -= job_vram
        self.cost_per_hour -= job_cost
        self.job_count -= 1

    # --- Verify real implementation ---

    @verify(target="scheduler.core.assign_job")
    def check_assign(self):
        """Prove that the real assign_job function respects this spec."""
        pass
```

### 7.2 A Real Implementation (What an LLM Might Generate)

```python
# scheduler/core.py
def assign_job(cluster_state: dict, job: dict) -> dict:
    """
    Cost-optimized job assignment.
    An LLM generated this — Praxis proves it's safe.
    """
    vram_available = cluster_state["vram_total"] - cluster_state["vram_used"]

    if job["vram_required"] > vram_available:
        raise InsufficientResourcesError(
            f"Need {job['vram_required']}GB, only {vram_available}GB free"
        )

    new_cost = cluster_state["cost_per_hour"] + job["cost_per_hour"]
    if new_cost > cluster_state["budget_per_hour"]:
        raise BudgetExceededError(
            f"Would exceed budget: ${new_cost}/hr > ${cluster_state['budget_per_hour']}/hr"
        )

    return {
        **cluster_state,
        "vram_used": cluster_state["vram_used"] + job["vram_required"],
        "cost_per_hour": new_cost,
        "job_count": cluster_state["job_count"] + 1,
    }
```

### 7.3 Expected Output

```
$ pytest tests/spec_gpu_scheduler.py -v --praxis

tests/spec_gpu_scheduler.py::GPUSchedulerSpec::invariant_no_overcommit PASSED
tests/spec_gpu_scheduler.py::GPUSchedulerSpec::invariant_non_negative_resources PASSED
tests/spec_gpu_scheduler.py::GPUSchedulerSpec::invariant_budget_respected PASSED
tests/spec_gpu_scheduler.py::GPUSchedulerSpec::transition_schedule_job PASSED
tests/spec_gpu_scheduler.py::GPUSchedulerSpec::transition_release_job PASSED
tests/spec_gpu_scheduler.py::GPUSchedulerSpec::verify_check_assign PASSED (symbolic)

6 passed in 2.34s
```

---

## 8. Package Structure

```
praxis/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/
│   └── praxis/
│       ├── __init__.py          # Public API: Spec, invariant, transition, verify
│       ├── types.py             # BoundedInt, Nat, BoundedFloat, Bool, Enum
│       ├── logic.py             # forall, exists, implies, iff, And, Or, Not
│       ├── spec.py              # Spec base class, metaclass, state field registry
│       ├── decorators.py        # @invariant, @transition, @verify, require()
│       ├── compiler/
│       │   ├── __init__.py
│       │   ├── extractor.py     # Phase 1: AST parse, extract specs
│       │   ├── lowering.py      # Phase 2: Python AST → Praxis IR (SSA)
│       │   ├── emitter.py       # Phase 3: IR → Z3 assertions
│       │   └── ir.py            # IR node definitions
│       ├── engine/
│       │   ├── __init__.py
│       │   ├── verifier.py      # Core verification loop (Z3 interaction)
│       │   ├── counterexample.py # Format counterexamples (human + JSON)
│       │   └── fallback.py      # Hypothesis-based fuzzing fallback
│       ├── pytest_plugin.py     # pytest integration (auto-registered)
│       └── cli.py               # `praxis check` CLI
├── tests/
│   ├── test_types.py            # Unit tests for type system
│   ├── test_compiler.py         # Unit tests for AST→Z3 translation
│   ├── test_verifier.py         # Integration tests for verification engine
│   ├── test_pytest_plugin.py    # Tests for pytest integration
│   ├── test_cli.py              # CLI tests
│   └── examples/
│       ├── spec_gpu_scheduler.py  # Reference example from section 7
│       ├── spec_bank_account.py   # Simple spec: balance >= 0
│       └── spec_rate_limiter.py   # Token bucket: tokens >= 0, <= max
├── docs/
│   ├── quickstart.md
│   ├── spec-language.md         # Complete DSL reference
│   ├── architecture.md          # Compiler & engine internals
│   └── agent-integration.md     # Using Praxis in LLM agent loops
└── examples/
    └── gpu_scheduler/
        ├── scheduler/
        │   └── core.py          # Example implementation
        └── tests/
            └── spec_scheduler.py # Example spec
```

---

## 9. Implementation Priorities (Build Order)

### Phase 1: Core (MVP — must work end-to-end)
1. `types.py` — `BoundedInt`, `Nat`, `BoundedFloat`, `Bool` with Z3 sort mapping
2. `logic.py` — `And`, `Or`, `Not`, `implies`, `forall` (bounded unrolling only)
3. `spec.py` — `Spec` metaclass that registers state fields and collects decorated methods
4. `decorators.py` — `@invariant`, `@transition`, `require()`
5. `compiler/extractor.py` — Walk a `Spec` subclass, extract invariant/transition ASTs
6. `compiler/lowering.py` — Translate Python AST to Z3 expressions (arithmetic, comparisons, boolean ops)
7. `compiler/emitter.py` — Generate Z3 solver calls, run check, extract counterexamples
8. `engine/verifier.py` — Orchestrate: extract → lower → emit → solve → report
9. `engine/counterexample.py` — Format results as human-readable + JSON

### Phase 2: Integration
10. `pytest_plugin.py` — pytest collection and reporting
11. `cli.py` — `praxis check` command

### Phase 3: Real Code Verification
12. `@verify(target=fn)` — Symbolic execution of target functions
13. `engine/fallback.py` — Hypothesis integration when symbolic exec fails

### Phase 4: Polish
14. Docs (quickstart, reference, architecture)
15. Examples (gpu_scheduler, bank_account, rate_limiter)
16. `pyproject.toml` — packaging, entry points, pytest plugin registration

---

## 10. Testing Requirements

The test suite is the most important artifact after the library itself. If we can't prove Praxis works, nobody should trust it to prove their code works. The suite is organized into four tiers of increasing severity.

### Tier 1: Unit Tests (per-module correctness)

Coverage targets: types.py 100%, compiler/*.py 100%, engine/*.py 95%+.

**types.py tests** (`tests/test_types.py`):
- Every type produces correct Z3 sort and constraints
- Edge cases: `BoundedInt[0, 0]` (single-value domain), `BoundedInt[-2**31, 2**31-1]` (full int range), `BoundedInt[-100, -1]` (all-negative domain)
- `BoundedFloat[0.0, 0.0]`, `BoundedFloat[-1e10, 1e10]`
- Type metadata is preserved through `__class_getitem__` (bounds accessible after parameterization)
- Invalid types raise clear errors: `BoundedInt[5, 3]` (lo > hi), `BoundedInt["a", "b"]` (non-numeric)

**logic.py tests** (`tests/test_logic.py`):
- Each combinator (`And`, `Or`, `Not`, `implies`, `forall`, `exists`) produces correct Z3 AST
- `forall` unrolls for range ≤ 50, uses `z3.ForAll` for range > 50
- `forall` over an empty range returns `True` (vacuous truth)
- `exists` over an empty range returns `False`
- Nested quantifiers: `forall(range(5), lambda i: exists(range(5), lambda j: ...))`
- `implies(False, anything)` is `True` (vacuous truth — verify Z3 agrees)

**compiler/lowering.py tests** (`tests/test_lowering.py`):
- Each supported Python AST node translates to correct IR
- Compound expressions: `(self.x + self.y) * 2 <= self.z - 1`
- Chained comparisons: `0 <= self.x <= 100` (Python parses this as `And(0 <= x, x <= 100)`)
- Ternary: `self.x if self.y > 0 else self.z`
- `require()` calls produce precondition IR nodes
- `self.field += expr` produces a PrimedVar assignment
- **Rejection tests**: for every unsupported construct, verify a clear `UnsupportedConstructError` is raised:
  - `for` loop inside invariant
  - `while` loop inside transition
  - `print()` call inside invariant
  - List comprehension (not over `forall`)
  - `import` statement inside method
  - `try/except` inside method
  - Attribute access on something other than `self` (e.g., `other.x`)
  - Nested function definition inside method
  - `await` / `async` inside method
  - Walrus operator `:=`

**compiler/emitter.py tests** (`tests/test_emitter.py`):
- Each IR node produces valid Z3 expression
- Generated Z3 programs are actually solvable (don't produce Z3 errors)
- Verify that emitted constraints for `BoundedInt[0, 100]` actually restrict the domain (Z3 should find no model for `x == 101`)

### Tier 2: Verification Correctness Tests (does the prover actually prove things?)

This is the critical tier. A bug here means Praxis gives false confidence.

**tests/test_verification_correctness.py** — each test case defines a spec AND the expected verification result. Praxis must agree with the expected result in every case.

**Specs that MUST pass (prover should confirm all invariants hold):**

1. **Trivial true**: `x: BoundedInt[0, 100]`, invariant: `self.x >= 0` — obviously true from the type bounds
2. **Tight arithmetic**: `x: BoundedInt[0, 100], y: BoundedInt[0, 100]`, invariant: `self.x + self.y <= 200` — tight but valid
3. **Transition preserves**: a `schedule_job` transition with correct `require()` guards that prevent overcommit
4. **Multiple invariants, all hold**: 3+ invariants on the same spec, all valid
5. **Transition with subtraction**: `release_job` that decrements — invariant `self.x >= 0` holds because of `require(self.x >= job_size)`
6. **Idempotent transition**: a transition that sets `self.x = self.x` preserves all invariants trivially
7. **Guard-heavy transition**: a transition with 4+ `require()` preconditions, all necessary

**Specs that MUST fail (prover should find counterexamples):**

8. **Missing guard**: `schedule_job` that does `self.vram_used += job_vram` without checking capacity — prover MUST find the overcommit
9. **Off-by-one**: guard checks `self.x + delta < self.max` instead of `<=` — prover must find the boundary case where `x + delta == max` and the invariant `x <= max` would be violated after a subsequent operation
10. **Wrong operator**: guard checks `self.x - delta >= 0` but transition does `self.x += delta` (copy-paste bug) — prover must catch
11. **Insufficient guard**: two invariants but the transition only guards against one — prover must find violation of the unguarded invariant
12. **Integer overflow in bounds**: `x: BoundedInt[0, 100], y: BoundedInt[0, 100]`, transition does `self.x += self.y` without guarding, invariant `self.x <= 100` — prover must find `x=50, y=60`
13. **Contradictory invariants**: `self.x > 50` AND `self.x < 50` — prover should report these cannot be simultaneously satisfied (UNSAT on the invariant consistency check, not on individual verification)
14. **Vacuous spec**: a spec with no invariants — should pass trivially (no properties to violate)

**Counterexample validation (the most important tests):**

15. **Round-trip test**: For every spec that FAILS, extract the counterexample, replay it concretely (actually call the transition function with those concrete values), and verify the invariant is indeed violated. If the counterexample doesn't reproduce concretely, Praxis has a soundness bug.
16. **Counterexample minimality**: Counterexamples should use small, human-readable values when possible (Z3 tends to do this naturally, but verify it).

### Tier 3: Stress Tests (adversarial and edge-case inputs)

**tests/test_stress.py** — push Praxis to its limits.

**Boundary arithmetic:**
1. `BoundedInt[0, 2**31-1]` — max 32-bit int, verify Z3 handles large constants
2. `BoundedInt[-2**31, 2**31-1]` — full signed 32-bit range
3. Invariant involving multiplication of two `BoundedInt[0, 1000]` values — product up to 1,000,000, verify Z3 handles it
4. Division: `self.x // self.y` where `y: BoundedInt[1, 100]` — verify no division by zero in Z3 encoding
5. Modulo: `self.x % self.y` — same

**Combinatorial blowup:**
6. Spec with 10 state fields, each `BoundedInt[0, 10]` — 10^10 state space, verify Z3 still completes within timeout
7. Spec with 20 invariants — verify all are checked, none are silently skipped
8. Spec with 10 transitions, each with 3 `require()` clauses — verify all are checked
9. `forall(range(100), lambda i: ...)` — verify unrolling or quantifier handling doesn't blow up
10. Nested `implies`: `implies(a, implies(b, implies(c, d)))` — 4 levels deep

**Pathological specs:**
11. Invariant that is a massive conjunction (20+ terms joined with `And`) — verify Z3 handles it
12. Invariant with deeply nested arithmetic: `((self.a + self.b) * (self.c - self.d)) // (self.e + 1) <= self.f`
13. Transition that mutates ALL state fields in a single transition
14. Spec where the invariant is satisfiable but the transition makes it unreachable (invariant holds trivially because no valid transition can be applied)
15. Two transitions where one's postcondition conflicts with the other's precondition — verify each is checked independently

**Error handling under stress:**
16. Z3 timeout: construct a spec that Z3 cannot solve in 1 second (e.g., quadratic arithmetic over large ranges). Verify Praxis returns UNKNOWN, doesn't crash, and falls back to fuzzing.
17. Malformed spec: class inherits from Spec but has no type annotations — verify clear error
18. Malformed spec: `@invariant` on a method that takes extra args beyond `self` — verify clear error
19. Malformed spec: `@transition` with a parameter that has no type annotation — verify clear error
20. Duplicate invariant names — verify clear error or correct handling

### Tier 4: End-to-End Confidence Tests

**tests/test_e2e.py** — full pipeline from Python spec to verdict.

**The "known answer" suite:**

These are hand-verified specs where we know the mathematically correct answer. They serve as regression tests — if any of these ever flip, something is fundamentally broken.

1. **Bank account** (balance >= 0): deposit always passes, withdraw with guard passes, withdraw WITHOUT guard fails with counterexample showing negative balance.

2. **GPU scheduler** (the reference example): full spec from section 7. All invariants pass. All transitions pass. Remove the capacity check from `schedule_job` — must fail with a counterexample showing overcommit.

3. **Rate limiter** (tokens in [0, max]): consume with guard passes, consume without guard fails. Refill with cap passes, refill without cap fails with counterexample showing tokens > max.

4. **Auction system**: `highest_bid: Nat`, `auction_open: Bool`. Invariant: `implies(not self.auction_open, self.highest_bid >= self.reserve_price)`. Transition `close_auction`: `require(self.highest_bid >= self.reserve_price)`, `self.auction_open = False`. Transition `place_bid(amount)`: `require(self.auction_open)`, `require(amount > self.highest_bid)`, `self.highest_bid = amount`. Must pass. Remove the reserve price check from close — must fail.

5. **Inventory system**: `stock: BoundedInt[0, 10000]`, `reserved: BoundedInt[0, 10000]`. Invariant: `self.reserved <= self.stock`. Transition `reserve(qty)`: `require(self.reserved + qty <= self.stock)`, `self.reserved += qty`. Transition `ship(qty)`: `require(qty <= self.reserved)`, `self.stock -= qty`, `self.reserved -= qty`. Must pass. Remove the check from `ship` — must fail with concrete counterexample.

**The "foolish LLM" suite:**

Simulate the kinds of bugs an LLM would actually introduce, and verify Praxis catches them.

6. **Forgot a guard entirely**: LLM generates `schedule_job` that just does the mutation with no checks.
7. **Checked the wrong variable**: guard checks `self.vram_total` instead of `self.vram_used` (plausible autocomplete error).
8. **Swapped > and <**: guard checks `self.vram_used + job_vram >= self.vram_total` instead of `<=` (directional bug).
9. **Guarded one invariant but not another**: two invariants, LLM only adds a require() for one.
10. **Used `=` semantics when they meant `+=`**: transition sets `self.vram_used = job_vram` instead of `self.vram_used += job_vram` — invariant about total consistency should fail.

**pytest plugin integration:**

11. Run the known-answer suite through the actual pytest plugin (not just the engine API). Verify test names, pass/fail counts, and output formatting match expectations.
12. Run with `--format json` via CLI, parse the output, verify it's valid JSON with correct schema.
13. Run with `--timeout 1` on the pathological timeout spec, verify graceful degradation.

### Testing Principles

- **No test should depend on Z3's specific counterexample values.** Assert that a counterexample EXISTS and that it VIOLATES the invariant when replayed. Don't assert `x == 48` — Z3 might pick a different valid counterexample.
- **Every "must fail" test must also verify the counterexample round-trips.** Extract the counterexample values, plug them into the invariant/transition concretely, confirm the violation is real.
- **Flaky tests are bugs.** Z3 is deterministic for the same input. If a test is flaky, the encoding is nondeterministic — find and fix it.
- **The test suite itself should run in under 60 seconds.** If any single test takes >5 seconds, it's a candidate for the timeout/stress category and should be marked accordingly.

---

## 11. Non-Goals for v1

- **Temporal logic** (`eventually`, `always`, `until`) — requires bounded model checking, out of scope
- **Composite types** (Set, Dict, List as spec fields) — requires Z3 array theory, significant complexity
- **Distributed specs** (multi-node reasoning) — future work
- **Automatic LLM loop** — users can build this on top; the core tool is the spec + verifier
- **IDE integration** (LSP, VS Code extension) — future work
- **Incremental verification** (re-check only changed specs) — future work

---

## 12. Design Principles

1. **Test tool first, formal methods tool never.** If a developer has to learn what "UNSAT" means, we failed.
2. **Readable specs are the product.** The DSL must be obvious to any Python developer. No ceremony.
3. **Counterexamples are the UX.** A failing spec without a clear counterexample is useless.
4. **Graceful degradation.** If Z3 can't prove it, fuzz it. Always give an answer.
5. **Agents are first-class consumers.** JSON output, structured errors, exit codes. The spec is the contract between human intent and agent execution.
6. **Zero config.** `pip install praxis`, write a spec, run `pytest`. Done.
