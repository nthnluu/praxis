# Triton GPU Kernel Configuration

## The Problem

Triton kernels process tensors in tiles. You pick a `BLOCK_SIZE`, compute `num_blocks = cdiv(n, BLOCK_SIZE)`, and launch. Get the grid dimensions wrong and the kernel doesn't crash — it just silently skips elements at the tail of the tensor. Your softmax looks fine on the first 1024 tokens. Token 1025 onward? Garbage.

This is the GPU version of an off-by-one error, except instead of a wrong index you get wrong results across an entire slice of your data. In production ML pipelines, this shows up as slightly degraded model quality that nobody notices until someone does an A/B test three months later.

The other common mistake: exceeding hardware limits on shared memory or threads per block. These at least give you an error at launch time — but only at runtime, and only on the specific GPU you're testing on. Different GPUs have different limits.

## The Implementation

`triton_kernel.py` — A `KernelLauncher` that models Triton kernel configuration:

```python
launcher = KernelLauncher(max_shared_memory=49152)
launcher.set_tensor(TensorDescriptor("activations", dim=50000))
launcher.configure_kernel(block_size=256)  # num_blocks auto-computed
launcher.allocate_shared_memory("reduction_buf", 8192)
config = launcher.launch()
```

Grid dimensions are recomputed on every configuration change — `resize_tensor`, `configure_kernel` — so coverage is maintained automatically. The `validate()` method checks all three invariants before any launch.

## The Spec

1. **`shared_memory_bounded`**: `shared_memory_per_block <= max_shared_memory`
2. **`threads_bounded`**: `threads_per_block <= 1024`
3. **`configure_kernel` guard**: `num_blocks * block_size >= tensor_dim` (full coverage)
4. **`resize_tensor` guard**: recomputed `num_blocks * block_size >= new_dim`

The coverage property involves multiplication — nonlinear arithmetic that makes Z3 work harder. We keep it in `require()` guards on transitions rather than as a standalone invariant, which keeps the solver in the linear fragment for the invariant checks while still catching the bug.

## The Bug Praxis Catches

In `broken/spec_triton_kernel.py`, `configure_kernel` doesn't check coverage:

```python
@transition
def configure_kernel(self, new_block_size, new_num_blocks):
    # Missing: require(new_num_blocks * new_block_size >= self.tensor_dim)
    self.block_size = new_block_size
    self.num_blocks = new_num_blocks
```

Praxis finds a counterexample like: `tensor_dim=3616`, `new_block_size=1023`, `new_num_blocks=3` — grid covers `3 * 1023 = 3069` elements but the tensor has 3616. The last 547 elements are never processed. No crash, no error, just silent data corruption.

Same bug in `resize_tensor`: the tensor grows but the grid doesn't keep up.

## Run It

```bash
praxis check examples/real_world/triton_kernel/
praxis check examples/real_world/triton_kernel/broken/
```
