"""Tests for target function verification and runtime guards."""

import pytest
from praxis import Spec, invariant, transition, require, runtime_guard
from praxis.types import BoundedInt
from praxis.engine.target_verifier import verify_target, _try_symbolic, _fuzz_target


# A simple spec
class BalanceSpec(Spec):
    balance: BoundedInt[0, 10000]

    @invariant
    def non_negative(self):
        return self.balance >= 0

    @transition
    def withdraw(self, amount: BoundedInt[1, 1000]):
        require(self.balance >= amount)
        self.balance -= amount


# ============================================================
# Runtime guard tests
# ============================================================

class BankAccount:
    def __init__(self, balance: int):
        self.balance = balance

    @runtime_guard(BalanceSpec, state_extractor=lambda self: {'balance': self.balance})
    def withdraw(self, amount: int):
        if self.balance < amount:
            raise ValueError("Insufficient funds")
        self.balance -= amount

    @runtime_guard(BalanceSpec, state_extractor=lambda self: {'balance': self.balance})
    def withdraw_broken(self, amount: int):
        # Bug: no balance check, can go negative
        self.balance -= amount


class TestRuntimeGuard:
    def test_correct_implementation_passes(self):
        account = BankAccount(100)
        account.withdraw(50)
        assert account.balance == 50

    def test_broken_implementation_caught(self):
        account = BankAccount(10)
        with pytest.raises(AssertionError, match="non_negative.*violated"):
            account.withdraw_broken(20)

    def test_guard_preserves_return_value(self):
        class Calculator:
            def __init__(self):
                self.balance = 100

            @runtime_guard(BalanceSpec, state_extractor=lambda self: {'balance': self.balance})
            def get_balance(self):
                return self.balance

        calc = Calculator()
        assert calc.get_balance() == 100

    def test_guard_marks_function(self):
        account = BankAccount(100)
        assert hasattr(BankAccount.withdraw, '_praxis_guarded')


class TestFuzzTarget:
    def test_fuzz_correct_function(self):
        def correct_withdraw(state):
            if state.balance >= 1:
                state.balance -= 1

        result = _fuzz_target(BalanceSpec, correct_withdraw, "test.correct_withdraw", fuzz_count=1000)
        assert result.status == "pass"

    def test_fuzz_broken_function(self):
        def broken_withdraw(state):
            state.balance -= 100  # Always subtract 100, no check

        result = _fuzz_target(BalanceSpec, broken_withdraw, "test.broken_withdraw", fuzz_count=1000)
        assert result.status == "fail"
        assert "violations" in result.message
