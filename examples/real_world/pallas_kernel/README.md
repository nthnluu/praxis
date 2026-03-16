# Pallas/XLA TPU Kernel Configuration

## The Problem

A Pallas kernel on a TPU has three ways to go wrong at configuration time, and all of them are silent until execution.

First, tiling. You pick a tile shape (say, 128x128) and a grid that tiles across your matrix. If the grid doesn't fully cover the matrix, you silently drop the rightmost columns or bottom rows. No error — just wrong results. The fix is simple arithmetic (grid_dim * tile_dim >= matrix_dim), but it's easy to mess up when tile sizes are tuned independently of matrix shapes, especially when an agent is generating kernel configs.

Second, HBM. TPU v4 has 32GB of HBM per chip. Your kernel's input buffers, output buffers, and scratch space all live there. Overcommit HBM and the kernel crashes at launch with a cryptic XLA error. Undercommit and you're leaving performance on the table. The budget math is straightforward — but nobody checks it at config time.

Third, pipelining. Pallas kernels can overlap DMA prefetch with compute by splitting work into microbatches across pipeline stages. If you have 4 pipeline stages but only 2 microbatches, two stages sit permanently idle. The pipeline never reaches steady state and you're paying the bubble overhead for nothing.

None of these bugs show up in unit tests with small matrices. They show up on a real TPU with production shapes, usually at 2 AM.

## The Implementation

`pallas_kernel.py` — A `PallasKernelConfig` with grid computation, HBM budget tracking, and pipeline scheduling:

```python
class PallasKernelConfig:
    def __init__(self, matrix_rows, matrix_cols, tile_rows, tile_cols, ...)
    def grid_shape(self) -> tuple[int, int]
    def utilization(self) -> float
    def make_hbm_budget(self) -> HBMBudget
    def make_pipeline(self) -> PipelineSchedule
```

`GridComputation` handles the tiling math. `HBMBudget` tracks named allocations against capacity. `PipelineSchedule` computes bubble fractions. No JAX dependency — this is pure config logic.

## The Spec

1. **`hbm_bounded`**: `hbm_usage_mb <= hbm_capacity_mb` — never overcommit HBM
2. **`pipeline_filled`**: `microbatches >= num_pipeline_stages` — enough work to fill the pipeline
3. **Grid coverage**: `grid_rows * tile_rows >= matrix_rows` (and cols) — enforced via `require()` in `configure_grid` because it's nonlinear

Grid coverage uses `require()` in transitions instead of a global `@invariant` because it involves multiplication. Z3 handles nonlinear integer arithmetic poorly in invariant checking (it has to prove the property holds for ALL reachable states). Putting the constraint in the transition is both faster and more precise.

## The Bug Praxis Catches

In `broken/spec_pallas_kernel.py`, `allocate_memory` is missing the HBM capacity check:

```python
@transition
def allocate_memory(self, usage: BoundedInt[0, 16384]):
    # Missing: require(usage <= self.hbm_capacity_mb)
    self.hbm_usage_mb = usage
```

Praxis finds: a TPU with 1 MB HBM capacity, then `allocate_memory(16384)` — 16 GB of HBM usage on a chip that can't hold it. In production, this is the kernel that works fine on a v4-8 (32 GB HBM) but crashes on a v3-8 (16 GB) because nobody checked the budget against the actual hardware.

## Run It

```bash
pytest examples/real_world/pallas_kernel/ -v
praxis check examples/real_world/pallas_kernel/
praxis check examples/real_world/pallas_kernel/broken/
```
