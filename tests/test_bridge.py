"""Tests for praxis.fuzz() and praxis.monitor() bridge APIs."""

import logging
import pytest

import praxis
from praxis import Spec, invariant, transition, require, fuzz, monitor
from praxis.types import BoundedInt, Nat


# A simple spec
class CounterSpec(Spec):
    count: Nat

    @invariant
    def non_negative(self):
        return self.count >= 0


# A correct implementation
class Counter:
    def __init__(self, initial: int = 0):
        self.count = initial

    def increment(self):
        self.count += 1

    def decrement(self):
        if self.count > 0:
            self.count -= 1

    def reset(self):
        self.count = 0


# A broken implementation
class BrokenCounter:
    def __init__(self, initial: int = 0):
        self.count = initial

    def increment(self):
        self.count += 1

    def decrement(self):
        self.count -= 1  # BUG: no guard, can go negative

    def reset(self):
        self.count = 0


class TestFuzz:
    def test_correct_impl_passes(self):
        counter = Counter(100)
        result = fuzz(
            counter,
            CounterSpec,
            state_extractor=lambda c: {"count": c.count},
            operations=[
                lambda c: c.increment(),
                lambda c: c.decrement(),
            ],
            iterations=1000,
            seed=42,
        )
        assert result.passed
        assert result.violations == 0

    def test_broken_impl_fails(self):
        counter = BrokenCounter(5)
        result = fuzz(
            counter,
            CounterSpec,
            state_extractor=lambda c: {"count": c.count},
            operations=[
                lambda c: c.increment(),
                lambda c: c.decrement(),
            ],
            iterations=1000,
            seed=42,
        )
        assert not result.passed
        assert result.violations > 0
        assert result.invariant_violated == "non_negative"
        assert result.first_violation is not None

    def test_no_operations_checks_current_state(self):
        counter = Counter(5)
        result = fuzz(
            counter,
            CounterSpec,
            state_extractor=lambda c: {"count": c.count},
            iterations=10,
        )
        assert result.passed

    def test_repr(self):
        result = fuzz(
            Counter(5),
            CounterSpec,
            state_extractor=lambda c: {"count": c.count},
            iterations=10,
        )
        assert "PASS" in repr(result)

    def test_seed_reproducible(self):
        def run():
            counter = BrokenCounter(3)
            return fuzz(
                counter, CounterSpec,
                state_extractor=lambda c: {"count": c.count},
                operations=[lambda c: c.decrement()],
                iterations=100, seed=123,
            )
        r1 = run()
        r2 = run()
        assert r1.violations == r2.violations


class TestMonitor:
    def test_monitor_log_mode(self, caplog):
        class MyCounter:
            def __init__(self):
                self.count = 5
            def bad_decrement(self):
                self.count -= 10  # goes negative

        monitor(
            MyCounter, CounterSpec,
            state_extractor=lambda self: {"count": self.count},
            methods=["bad_decrement"],
            mode="log",
        )
        c = MyCounter()
        with caplog.at_level(logging.WARNING):
            c.bad_decrement()  # should log, not raise
        assert "non_negative" in caplog.text
        assert c.count == -5  # mutation happened

    def test_monitor_enforce_mode(self):
        class MyCounter2:
            def __init__(self):
                self.count = 5
            def bad_decrement(self):
                self.count -= 10

        monitor(
            MyCounter2, CounterSpec,
            state_extractor=lambda self: {"count": self.count},
            methods=["bad_decrement"],
            mode="enforce",
        )
        c = MyCounter2()
        with pytest.raises(AssertionError, match="non_negative"):
            c.bad_decrement()

    def test_monitor_off_mode(self):
        class MyCounter3:
            def __init__(self):
                self.count = 5
            def bad_decrement(self):
                self.count -= 10

        monitor(
            MyCounter3, CounterSpec,
            state_extractor=lambda self: {"count": self.count},
            methods=["bad_decrement"],
            mode="off",
        )
        c = MyCounter3()
        c.bad_decrement()  # no raise, no log
        assert c.count == -5

    def test_monitor_correct_impl_no_warnings(self, caplog):
        class GoodCounter:
            def __init__(self):
                self.count = 5
            def decrement(self):
                if self.count > 0:
                    self.count -= 1

        monitor(
            GoodCounter, CounterSpec,
            state_extractor=lambda self: {"count": self.count},
            methods=["decrement"],
        )
        c = GoodCounter()
        with caplog.at_level(logging.WARNING):
            for _ in range(10):
                c.decrement()
        assert "non_negative" not in caplog.text
