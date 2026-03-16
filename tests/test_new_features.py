"""Tests for new features: enums, custom messages, conditional invariants."""

import z3
import pytest

from praxis import Spec, invariant, transition, implies
from praxis.types import BoundedInt, PraxisEnum
from praxis.decorators import require
from praxis.engine.verifier import verify_spec
from praxis.engine.counterexample import Counterexample


# ============================================================
# Enum Types (3.2)
# ============================================================

class OrderStatus(PraxisEnum):
    PENDING = 0
    CONFIRMED = 1
    SHIPPED = 2
    DELIVERED = 3


class TestEnumType:
    def test_enum_has_praxis_type(self):
        assert OrderStatus._praxis_type == "Enum"

    def test_enum_values(self):
        assert OrderStatus._enum_values == {
            "PENDING": 0, "CONFIRMED": 1, "SHIPPED": 2, "DELIVERED": 3
        }

    def test_enum_to_z3(self):
        var, constraints = OrderStatus.to_z3("status")
        assert isinstance(var, z3.ArithRef)
        assert len(constraints) == 1  # membership constraint

    def test_enum_z3_restricts_values(self):
        var, constraints = OrderStatus.to_z3("status")
        s = z3.Solver()
        s.add(*constraints)
        s.add(var == 5)  # not a valid enum value
        assert s.check() == z3.unsat

    def test_enum_z3_allows_valid(self):
        var, constraints = OrderStatus.to_z3("status")
        s = z3.Solver()
        s.add(*constraints)
        s.add(var == 2)  # SHIPPED
        assert s.check() == z3.sat

    def test_enum_comparison_constants(self):
        assert OrderStatus.PENDING == 0
        assert OrderStatus.DELIVERED == 3

    def test_enum_in_spec(self):
        class OrderSpec(Spec):
            status: OrderStatus

            @invariant
            def valid_status(self):
                return self.status >= 0

            @transition
            def confirm(self, dummy: BoundedInt[0, 0]):
                require(self.status == 0)  # PENDING
                self.status = 1  # CONFIRMED

        result = verify_spec(OrderSpec)
        assert result.passed

    def test_enum_backward_transition_caught(self):
        class BadOrderSpec(Spec):
            status: OrderStatus

            @invariant
            def only_forward(self):
                return self.status >= 0

            @transition
            def go_back(self, dummy: BoundedInt[0, 0]):
                # Goes from any state to -1 — violates invariant
                self.status = self.status - 2

        result = verify_spec(BadOrderSpec)
        assert not result.passed


# ============================================================
# Custom Error Messages (3.4)
# ============================================================

class TestCustomMessages:
    def test_invariant_with_message(self):
        @invariant(message="CRITICAL: resource overcommit")
        def no_overcommit(self):
            return self.x >= 0

        assert no_overcommit._praxis_invariant is True
        assert no_overcommit._praxis_invariant_message == "CRITICAL: resource overcommit"

    def test_invariant_without_message(self):
        @invariant
        def simple(self):
            return self.x >= 0

        assert simple._praxis_invariant is True
        assert simple._praxis_invariant_message is None

    def test_message_in_counterexample_human(self):
        ce = Counterexample(
            spec_name="TestSpec",
            property_name="bounded",
            kind="invariant_violation",
            transition="update",
            before={"x": 100},
            inputs={"v": 10},
            after={"x": 110},
            message="CRITICAL: value exceeds maximum",
        )
        text = ce.to_human()
        assert "CRITICAL: value exceeds maximum" in text

    def test_message_in_counterexample_json(self):
        ce = Counterexample(
            spec_name="TestSpec",
            property_name="bounded",
            kind="invariant_violation",
            message="CRITICAL: value exceeds maximum",
        )
        j = ce.to_json()
        assert j["message"] == "CRITICAL: value exceeds maximum"

    def test_no_message_not_in_json(self):
        ce = Counterexample(
            spec_name="TestSpec",
            property_name="bounded",
            kind="invariant_violation",
        )
        j = ce.to_json()
        assert "message" not in j


# ============================================================
# Conditional Invariants (3.3)
# ============================================================

class TestConditionalInvariants:
    def test_implies_in_invariant(self):
        """implies() works end-to-end in invariant verification."""

        class ConditionalSpec(Spec):
            x: BoundedInt[0, 100]
            y: BoundedInt[0, 100]

            @invariant
            def if_high_then_y_positive(self):
                return implies(self.x > 50, self.y >= 0)

        result = verify_spec(ConditionalSpec)
        assert result.passed

    def test_implies_with_transition(self):
        """Conditional invariant preserved by guarded transition."""

        class GuardedSpec(Spec):
            active: BoundedInt[0, 1]
            value: BoundedInt[0, 100]

            @invariant
            def active_implies_positive(self):
                return implies(self.active == 1, self.value > 0)

            @transition
            def activate(self, v: BoundedInt[1, 100]):
                require(v > 0)
                self.active = 1
                self.value = v

            @transition
            def deactivate(self, dummy: BoundedInt[0, 0]):
                self.active = 0
                self.value = 0

        result = verify_spec(GuardedSpec)
        assert result.passed
