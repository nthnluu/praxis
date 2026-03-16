# Integrate with agents

Praxis outputs structured JSON for consumption by LLM agents. Use `praxis check` to verify spec models, `praxis verify` to test implementations against specs, and `praxis explain` to generate human-readable or JSON descriptions.

## Get JSON output

```bash
praxis check tests/spec_scheduler.py --format json
```

### Passing result

```json
[
  {
    "spec": "GPUSchedulerSpec",
    "passed": true,
    "results": [
      {"property": "no_overcommit", "kind": "invariant", "status": "pass"},
      {"property": "schedule_job", "kind": "transition", "status": "pass"}
    ]
  }
]
```

### Failing result

```json
{
  "property": "no_overcommit",
  "kind": "transition",
  "status": "fail",
  "transition": "schedule_job",
  "counterexample": {
    "status": "FAIL",
    "spec": "GPUSchedulerSpec",
    "property": "no_overcommit",
    "counterexample": {
      "before": {"vram_total": 80, "vram_used": 48},
      "inputs": {"job_vram": 40},
      "after": {"vram_used": 88}
    }
  }
}
```

## Verify implementations with `praxis verify`

Use `praxis verify` to test that a real implementation follows a spec. This runs the spec's fuzz-based checks against the target function.

```bash
praxis verify specs/spec_scheduler.py --target myapp.scheduler.GPUScheduler --format json
```

The `--target` flag takes a dotted path to the implementation class or function. Praxis imports it and runs fuzz testing against the spec's invariants.

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--target` | Dotted path to implementation | Required |
| `--format` | Output format (`human` or `json`) | `human` |
| `--timeout` | Per-property timeout in seconds | `30` |
| `--fuzz` | Fuzz iteration count | `10000` |

## Explain specs with `praxis explain`

Use `praxis explain` to generate a natural-language or JSON summary of a spec. Useful for agents that need to understand what a spec requires before generating an implementation.

```bash
# Human-readable summary
praxis explain specs/spec_scheduler.py

# JSON for agent consumption
praxis explain specs/spec_scheduler.py --format json
```

## Implement an agent loop

The full agent workflow has four steps: explain, implement, verify, fix.

1. **Explain**: Run `praxis explain specs/spec.py --format json` to get a structured description of the spec. Feed this to the agent as context.
2. **Implement**: The agent generates implementation code based on the spec description.
3. **Verify**: Run `praxis check specs/spec.py --format json` to verify the spec model, then run `praxis verify specs/spec.py --target myapp.module.Class --format json` to test the implementation.
4. **Fix**: If failures exist, feed the counterexample back to the agent. The agent fixes the code. Repeat steps 3-4 until all checks pass.

### Example agent loop (pseudocode)

```python
# Step 1: Get spec description
spec_info = run("praxis explain specs/spec.py --format json")
agent.send(f"Implement this spec:\n{spec_info}")

# Step 2: Agent generates code
code = agent.receive()
save(code, "myapp/module.py")

# Step 3-4: Verify and fix loop
while True:
    result = run("praxis verify specs/spec.py --target myapp.module.Class --format json")
    if result["passed"]:
        break
    agent.send(f"Fix this violation:\n{json.dumps(result)}")
    code = agent.receive()
    save(code, "myapp/module.py")
```

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | All checks passed |
| `1` | One or more checks failed |
| `2` | Error (bad spec, file not found) |
