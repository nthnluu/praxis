# Contributing to Praxis

## Setup

```bash
git clone <repo-url>
cd praxis
pip install -e ".[dev]"
pytest tests/ -v  # should see 250+ tests pass in <1s
```

## Running Tests

```bash
# Full suite
pytest tests/ -v

# Specific module
pytest tests/test_lowering.py -v

# Example specs (run as live verification via pytest plugin)
pytest examples/ -v

# Broken variants should FAIL (they test that Praxis catches bugs)
praxis check examples/real_world/auth_state_machine/broken/
```

Test files mirror source modules: `test_lowering.py` tests `compiler/lowering.py`, `test_emitter.py` tests `compiler/emitter.py`, etc.

## Architecture

The compiler pipeline:

```
Spec subclass → extractor.py → lowering.py → emitter.py → verifier.py → result
                (Python AST)    (Praxis IR)   (Z3 exprs)   (SAT/UNSAT)
```

1. **`spec.py`** — `Spec` base class collects fields, invariants, transitions via `__init_subclass__`
2. **`compiler/extractor.py`** — `extract_spec()` uses `inspect.getsource` + `ast.parse` to get method ASTs
3. **`compiler/lowering.py`** — Translates Python AST → Praxis IR nodes (defined in `compiler/ir.py`)
4. **`compiler/emitter.py`** — Translates IR nodes → Z3 expressions
5. **`engine/verifier.py`** — Orchestrates Z3 solving, produces counterexamples on failure

See `docs/architecture.md` for details.

## Adding a New AST Construct

To support a new Python construct (e.g., a new operator):

1. **`compiler/ir.py`** — Add a frozen dataclass IR node
2. **`compiler/lowering.py`** — Add a case in `_lower_expr()` that produces your IR node
3. **`compiler/emitter.py`** — Add a case in `emit()` that translates your IR node to Z3
4. **`tests/test_lowering.py`** — Test that the Python AST lowers correctly
5. **`tests/test_emitter.py`** — Test that the IR emits correct Z3

## Intentionally Unsupported Constructs

These are **by design**, not missing features. They raise `UnsupportedConstructError` with actionable messages:

- `for`/`while` loops — use `forall()`/`exists()` for quantification
- Function calls (except `require`, `And`, `Or`, `Not`, `implies`, `iff`)
- String/container operations — model by numeric properties (length, count)
- I/O, imports, `try`/`except` inside spec methods

## Good First Issues

- Improve error messages for common mistakes
- Add more examples in `examples/real_world/`
- Add tests for edge cases (see `tests/test_edge_cases.py` for the pattern)

## Key Implementation Details

**Primed variable aliasing in `verifier.py`**: When verifying transitions, the verifier creates an `after_ctx` by aliasing `ctx.primed` as `after_ctx.vars`. This lets the emitter evaluate invariants over the after-state (primed variables) using the same code path as the before-state. If you modify transition verification, be careful not to break this aliasing.

**Primed variable bounds**: The verifier intentionally does NOT add type-bound constraints on primed (after-state) variables. The invariants themselves are what we check on the after-state — adding bounds would hide real violations.

## Code Style

- Type hints on all public function signatures (Python 3.11+ syntax)
- Docstrings on all public classes and functions
- No bare `except:` — use specific exception types
- Error messages should be actionable ("Use `self.x` instead of `x`", not "Invalid reference")
