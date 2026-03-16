# Why Praxis exists

## The trust problem

LLM-generated code is probabilistic. It produces plausible code that usually works. But "usually" is insufficient for systems that manage money, allocate GPU resources, or control infrastructure.

Traditional testing checks examples: "does `withdraw(50)` from `balance=100` give 50?" Property-based testing checks random samples: "for 10,000 random withdrawals, does balance stay non-negative?" Both build confidence. Neither provides certainty.

Praxis narrows the gap. When Praxis reports that an invariant holds, it means the *spec model* is consistent and every transition preserves that invariant for all inputs within declared type bounds -- not a sample. `runtime_guard` then monitors the implementation against those same invariants at runtime, catching any divergence between the model and the real code.

## The logic cage

The core idea: you don't need to verify implementation correctness. You need to verify that the implementation stays within safe boundaries.

A spec defines a logic cage -- a set of invariants that must never be violated, regardless of what the implementation does. Inside the cage, the implementation (human or AI) has full creative freedom. The cage guarantees safety.

```
+-------------------------------------+
|           Logic Cage                |
|                                     |
|  Invariant: balance >= 0            |
|  Invariant: total_in == total_out   |
|                                     |
|  +-----------------------------+    |
|  |   Implementation            |    |
|  |   (any approach works,      |    |
|  |    as long as it stays      |    |
|  |    inside the cage)         |    |
|  +-----------------------------+    |
+-------------------------------------+
```

## The trust triangle

Three participants, three artifacts:

1. **Human** writes the spec (readable Python, ~20 lines)
2. **Agent** writes the implementation (creative, optimized, potentially complex)
3. **Praxis** checks the boundary between them:
   - The **prover** verifies the spec model -- that transitions preserve invariants for all inputs within declared bounds (bounded model checking of specification consistency and inductive invariant preservation)
   - The **runtime guard** monitors the implementation -- checking the spec's invariants against live state on every guarded call

There is an honest gap between these two layers. The prover checks the spec's *logic*, not the implementation's *code*. The runtime guard checks the implementation's *behavior*, but only on paths that actually execute. Together they cover more ground than either alone, but neither is omniscient.

The human doesn't need to read the implementation. The agent doesn't need to understand the spec's intent. The prover checks the model; `runtime_guard` watches the code.

This is how you scale trust in AI-generated code: not by hoping the AI is correct, but by checking the spec's logic and monitoring the implementation against it.

## Why not test more?

Testing tells you "I couldn't find a bug." Specification checking tells you "there is no bug in this model, within these bounds." Runtime monitoring tells you "the implementation hasn't violated the spec yet, on the paths I've seen."

The difference matters when:

- The state space is large (10 fields x 100 values each = 10^20 states)
- The bugs are at boundaries (off-by-one in a capacity check)
- The cost of failure is high (GPU kernel crash, negative bank balance, data corruption)

Praxis doesn't replace testing. It handles the invariants that must not fail, while tests handle behavior, performance, and integration.

## Zero ceremony

Praxis is a test tool, not a proof assistant. You never write a lemma, a tactic, or a proof term. You write Python, run pytest, and read green/red output. If it's red, you get a concrete counterexample showing exactly how the invariant can be violated.

The spec is the documentation. The counterexample is the bug report. The verification is the test.
