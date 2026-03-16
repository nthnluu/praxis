"""Tests for praxis.decorators."""

import pytest
from praxis.decorators import invariant, transition, verify, require


class TestInvariant:
    def test_marks_method(self):
        @invariant
        def my_inv(self):
            return True
        assert my_inv._praxis_invariant is True

    def test_preserves_callable(self):
        @invariant
        def my_inv(self):
            return 42
        assert my_inv(None) == 42


class TestTransition:
    def test_marks_method(self):
        @transition
        def my_trans(self, x: int):
            pass
        assert my_trans._praxis_transition is True


class TestVerify:
    def test_marks_method(self):
        @verify(target="my.module.func")
        def my_check(self):
            pass
        assert my_check._praxis_verify is True
        assert my_check._praxis_verify_target == "my.module.func"


class TestRequire:
    def test_true_passes(self):
        require(True)
        require(1)
        require("nonempty")

    def test_false_raises(self):
        with pytest.raises(AssertionError, match="Precondition violated"):
            require(False)

    def test_zero_raises(self):
        with pytest.raises(AssertionError):
            require(0)
