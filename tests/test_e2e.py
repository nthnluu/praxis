"""Tier 4: End-to-end confidence tests — full pipeline with known answers."""

from praxis import Spec, invariant, transition, And, implies
from praxis.types import BoundedInt, BoundedFloat, Nat, Bool
from praxis.decorators import require
from praxis.engine.verifier import verify_spec


# ============================================================
# KNOWN-ANSWER SPECS
# ============================================================

# --- Bank Account ---

class BankAccountCorrectSpec(Spec):
    balance: BoundedInt[0, 10000]

    @invariant
    def non_negative(self):
        return self.balance >= 0

    @transition
    def deposit(self, amount: BoundedInt[1, 1000]):
        require(self.balance + amount <= 10000)
        self.balance += amount

    @transition
    def withdraw(self, amount: BoundedInt[1, 1000]):
        require(self.balance >= amount)
        self.balance -= amount


class BankAccountBrokenSpec(Spec):
    balance: BoundedInt[0, 10000]

    @invariant
    def non_negative(self):
        return self.balance >= 0

    @transition
    def deposit(self, amount: BoundedInt[1, 1000]):
        require(self.balance + amount <= 10000)
        self.balance += amount

    @transition
    def withdraw(self, amount: BoundedInt[1, 1000]):
        # Missing: require(self.balance >= amount)
        self.balance -= amount


# --- GPU Scheduler ---

class GPUSchedulerCorrectSpec(Spec):
    vram_used: BoundedInt[0, 640]
    vram_total: BoundedInt[0, 640]

    @invariant
    def no_overcommit(self):
        return self.vram_used <= self.vram_total

    @invariant
    def non_negative_usage(self):
        return self.vram_used >= 0

    @transition
    def schedule_job(self, job_vram: BoundedInt[1, 80]):
        require(self.vram_used + job_vram <= self.vram_total)
        self.vram_used += job_vram

    @transition
    def release_job(self, job_vram: BoundedInt[1, 80]):
        require(self.vram_used >= job_vram)
        self.vram_used -= job_vram


class GPUSchedulerBrokenSpec(Spec):
    vram_used: BoundedInt[0, 640]
    vram_total: BoundedInt[0, 640]

    @invariant
    def no_overcommit(self):
        return self.vram_used <= self.vram_total

    @invariant
    def non_negative_usage(self):
        return self.vram_used >= 0

    @transition
    def schedule_job(self, job_vram: BoundedInt[1, 80]):
        # Missing guard!
        self.vram_used += job_vram

    @transition
    def release_job(self, job_vram: BoundedInt[1, 80]):
        require(self.vram_used >= job_vram)
        self.vram_used -= job_vram


# --- Rate Limiter ---

class RateLimiterCorrectSpec(Spec):
    tokens: BoundedInt[0, 100]
    max_tokens: BoundedInt[1, 100]

    @invariant
    def tokens_bounded(self):
        return self.tokens <= self.max_tokens

    @transition
    def consume(self, n: BoundedInt[1, 10]):
        require(self.tokens >= n)
        self.tokens -= n

    @transition
    def refill(self, n: BoundedInt[1, 10]):
        require(self.tokens + n <= self.max_tokens)
        self.tokens += n


class RateLimiterBrokenConsumeSpec(Spec):
    tokens: BoundedInt[0, 100]
    max_tokens: BoundedInt[1, 100]

    @invariant
    def tokens_non_negative(self):
        return self.tokens >= 0

    @transition
    def consume(self, n: BoundedInt[1, 10]):
        # Missing guard
        self.tokens -= n


class RateLimiterBrokenRefillSpec(Spec):
    tokens: BoundedInt[0, 100]
    max_tokens: BoundedInt[1, 100]

    @invariant
    def tokens_bounded(self):
        return self.tokens <= self.max_tokens

    @transition
    def refill(self, n: BoundedInt[1, 100]):
        # Missing cap guard
        self.tokens += n


# --- Inventory System ---

class InventoryCorrectSpec(Spec):
    stock: BoundedInt[0, 10000]
    reserved: BoundedInt[0, 10000]

    @invariant
    def reserved_within_stock(self):
        return self.reserved <= self.stock

    @transition
    def reserve(self, qty: BoundedInt[1, 100]):
        require(self.reserved + qty <= self.stock)
        self.reserved += qty

    @transition
    def ship(self, qty: BoundedInt[1, 100]):
        require(qty <= self.reserved)
        self.stock -= qty
        self.reserved -= qty


class InventoryBrokenSpec(Spec):
    stock: BoundedInt[0, 10000]
    reserved: BoundedInt[0, 10000]

    @invariant
    def reserved_within_stock(self):
        return self.reserved <= self.stock

    @transition
    def reserve(self, qty: BoundedInt[1, 100]):
        # Missing: require(self.reserved + qty <= self.stock)
        self.reserved += qty

    @transition
    def ship(self, qty: BoundedInt[1, 100]):
        require(qty <= self.reserved)
        self.stock -= qty
        self.reserved -= qty


# ============================================================
# FOOLISH LLM SUITE
# ============================================================

class ForgotGuardSpec(Spec):
    """f. Forgot a guard entirely."""
    x: BoundedInt[0, 100]

    @invariant
    def bounded(self):
        return self.x <= 100

    @transition
    def update(self, v: BoundedInt[1, 50]):
        self.x += v


class WrongVariableLLMSpec(Spec):
    """g. Checked wrong variable (autocomplete bug)."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def y_bounded(self):
        return self.y <= 100

    @transition
    def update(self, v: BoundedInt[1, 50]):
        require(self.x + v <= 100)  # checks x instead of y
        self.y += v


class SwappedOperatorSpec(Spec):
    """h. Swapped > and < (directional bug)."""
    x: BoundedInt[0, 100]

    @invariant
    def bounded(self):
        return self.x <= 100

    @transition
    def update(self, v: BoundedInt[1, 50]):
        require(self.x + v >= 100)  # Wrong direction! should be <=
        self.x += v


class OneGuardedSpec(Spec):
    """i. Guarded one invariant but not another."""
    x: BoundedInt[0, 100]
    y: BoundedInt[0, 100]

    @invariant
    def x_bounded(self):
        return self.x <= 100

    @invariant
    def y_bounded(self):
        return self.y <= 100

    @transition
    def update(self, v: BoundedInt[1, 50]):
        require(self.x + v <= 100)
        self.x += v
        self.y += v  # y not guarded


class AssignInsteadOfPlusEqualsSpec(Spec):
    """j. Used = when meant += ."""
    total: BoundedInt[0, 10000]
    count: BoundedInt[0, 100]

    @invariant
    def total_grows(self):
        return self.total >= self.count

    @transition
    def add_item(self, value: BoundedInt[1, 100]):
        self.total = value  # Bug: should be self.total += value
        self.count += 1


# ============================================================
# TESTS
# ============================================================

class TestKnownAnswerSuite:
    def test_bank_correct(self):
        result = verify_spec(BankAccountCorrectSpec)
        assert result.passed, _failures(result)

    def test_bank_broken(self):
        result = verify_spec(BankAccountBrokenSpec)
        assert not result.passed
        _verify_has_transition_failure(result, "withdraw")
        _roundtrip(BankAccountBrokenSpec, result, "withdraw", "non_negative")

    def test_gpu_correct(self):
        result = verify_spec(GPUSchedulerCorrectSpec)
        assert result.passed, _failures(result)

    def test_gpu_broken(self):
        result = verify_spec(GPUSchedulerBrokenSpec)
        assert not result.passed
        _verify_has_transition_failure(result, "schedule_job")

    def test_rate_limiter_correct(self):
        result = verify_spec(RateLimiterCorrectSpec)
        assert result.passed, _failures(result)

    def test_rate_limiter_broken_consume(self):
        result = verify_spec(RateLimiterBrokenConsumeSpec)
        assert not result.passed
        _verify_has_transition_failure(result, "consume")

    def test_rate_limiter_broken_refill(self):
        result = verify_spec(RateLimiterBrokenRefillSpec)
        assert not result.passed
        _verify_has_transition_failure(result, "refill")

    def test_inventory_correct(self):
        result = verify_spec(InventoryCorrectSpec)
        assert result.passed, _failures(result)

    def test_inventory_broken(self):
        result = verify_spec(InventoryBrokenSpec)
        assert not result.passed
        _verify_has_transition_failure(result, "reserve")


class TestFoolishLLMSuite:
    def test_forgot_guard(self):
        result = verify_spec(ForgotGuardSpec)
        assert not result.passed

    def test_wrong_variable(self):
        result = verify_spec(WrongVariableLLMSpec)
        assert not result.passed

    def test_swapped_operator(self):
        result = verify_spec(SwappedOperatorSpec)
        assert not result.passed

    def test_one_guarded(self):
        result = verify_spec(OneGuardedSpec)
        assert not result.passed

    def test_assign_instead_of_plus_equals(self):
        result = verify_spec(AssignInsteadOfPlusEqualsSpec)
        assert not result.passed


# ============================================================
# Helpers
# ============================================================

def _failures(result):
    return [
        f"{r.property_name}: {r.status} - {r.error_message or ''}"
        for r in result.results if r.status != "pass"
    ]


def _verify_has_transition_failure(result, transition_name):
    fails = [r for r in result.results if r.status == "fail" and r.transition_name == transition_name]
    assert len(fails) >= 1, f"No failure for transition {transition_name}: {_failures(result)}"
    for f in fails:
        assert f.counterexample is not None


def _roundtrip(spec_cls, result, transition_name, invariant_name):
    """Verify counterexample concretely violates the invariant."""
    fails = [r for r in result.results if r.status == "fail" and r.transition_name == transition_name]
    for fail in fails:
        ce = fail.counterexample
        inv_method = None
        for i in spec_cls.invariants():
            if i.__name__ == invariant_name:
                inv_method = i
                break
        if inv_method is None:
            continue
        obj = type("State", (), {})()
        for name, val in ce.before.items():
            setattr(obj, name, val)
        for name, val in ce.after.items():
            setattr(obj, name, val)
        assert not inv_method(obj), (
            f"SOUNDNESS BUG: counterexample doesn't violate {invariant_name}"
        )
