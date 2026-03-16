# Architecture

## Pipeline

```
Spec subclass -> Extractor -> Lowering -> Emitter -> Z3 Solver -> Result
                                                                     |
                                                              Bridge module
                                                            /      |       \
                                                        fuzz()  monitor()  @runtime_guard
```

### 1. Extractor (`compiler/extractor.py`)

Walks a `Spec` subclass using `inspect.getsource()` and `ast.parse()`. Extracts:

- State fields (type annotations)
- Invariant methods (AST)
- Transition methods (AST + parameter types)
- Initial state predicates (AST)

### 2. Lowering (`compiler/lowering.py`)

Translates Python AST to Praxis IR (defined in `compiler/ir.py`):

- `self.field` -> `Var(name)`
- `param` -> `Param(name)`
- `a + b` -> `BinOp("+", a, b)`
- `require(expr)` -> `Require(expr)`
- `self.field += expr` -> `Assign(field, BinOp("+", Var(field), expr))`

Unsupported constructs raise `UnsupportedConstructError` with actionable messages.

### 3. Emitter (`compiler/emitter.py`)

Translates IR nodes to Z3 expressions using an `EmitContext` that tracks variable bindings.

### 4. Verifier (`engine/verifier.py`)

Orchestrates verification:

1. **Invariant checks** -- Determines whether invariants are consistent (simultaneously satisfiable).
2. **Initial state checks** -- Determines whether every initial state (defined by `@initial` predicates) satisfies all invariants (induction base case).
3. **Transition checks** -- Determines whether each transition preserves all invariants:
   - Assumes invariants hold in the before-state
   - Assumes preconditions (`require`)
   - Applies the transition (primed variables)
   - Checks invariants on the after-state

### 5. Counterexample (`engine/counterexample.py`)

When Z3 finds a SAT result (violation), this module extracts concrete values and formats them as human-readable text or JSON.

### 6. Fallback (`engine/fallback.py`)

When Z3 returns UNKNOWN (timeout), Praxis falls back to random testing using Hypothesis strategies derived from Praxis types.

### 7. Bridge (`bridge.py`)

Connects specs to implementations. The bridge provides three connection modes:

- **`fuzz()`** -- test-time checking. Runs random sequences of operations on an implementation object, checking spec invariants after each operation. Use in test suites.
- **`monitor()`** -- runtime checking. Wraps methods on an implementation class to check spec invariants after each call. Attach at startup or in `conftest.py`. Supports `log`, `enforce`, and `off` modes.
- **`@runtime_guard`** -- per-method decorator. More coupled than `fuzz()` or `monitor()` because the implementation must reference the decorator directly.

The bridge keeps the implementation decoupled from the spec. The implementation never imports `praxis` (unless you use `@runtime_guard`). The connection lives in tests or config.
