"""GPU job scheduler — example implementation."""


class InsufficientResourcesError(Exception):
    pass


class BudgetExceededError(Exception):
    pass


def assign_job(cluster_state: dict, job: dict) -> dict:
    """Cost-optimized job assignment."""
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
