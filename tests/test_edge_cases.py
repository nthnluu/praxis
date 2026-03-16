"""Edge case tests for spec construction and verification."""

import pytest

from praxis import Spec, invariant, transition, And
from praxis.types import BoundedInt
from praxis.decorators import require
from praxis.engine.verifier import verify_spec


class TestMinimalSpec:
    """Spec with exactly one field and one invariant."""

    def test_minimal_passes(self):
        class MinSpec(Spec):
            x: BoundedInt[0, 10]

            @invariant
            def bounded(self):
                return self.x >= 0

        result = verify_spec(MinSpec)
        assert result.passed


class TestSpecInheritance:
    """Spec that inherits from another spec."""

    def test_child_inherits_parent_invariants(self):
        class ParentSpec(Spec):
            x: BoundedInt[0, 100]

            @invariant
            def x_non_negative(self):
                return self.x >= 0

        class ChildSpec(ParentSpec):
            y: BoundedInt[0, 100]

            @invariant
            def y_non_negative(self):
                return self.y >= 0

        # Child should have both fields
        fields = ChildSpec.state_fields()
        assert "x" in fields
        assert "y" in fields

        # Child should have both invariants
        invs = ChildSpec.invariants()
        names = {m.__name__ for m in invs}
        assert "x_non_negative" in names
        assert "y_non_negative" in names

    def test_child_inherits_transitions(self):
        class ParentSpec(Spec):
            x: BoundedInt[0, 100]

            @invariant
            def bounded(self):
                return self.x <= 100

            @transition
            def parent_update(self, v: BoundedInt[1, 10]):
                require(self.x + v <= 100)
                self.x += v

        class ChildSpec(ParentSpec):
            @transition
            def child_update(self, v: BoundedInt[1, 5]):
                require(self.x + v <= 100)
                self.x += v

        trans = ChildSpec.transitions()
        names = {m.__name__ for m in trans}
        assert "parent_update" in names
        assert "child_update" in names

    def test_parent_verifies_independently(self):
        class ParentSpec(Spec):
            x: BoundedInt[0, 100]

            @invariant
            def bounded(self):
                return self.x >= 0

        result = verify_spec(ParentSpec)
        assert result.passed

    def test_child_verifies_with_inherited(self):
        class ParentSpec(Spec):
            x: BoundedInt[0, 100]

            @invariant
            def x_bounded(self):
                return self.x >= 0

        class ChildSpec(ParentSpec):
            y: BoundedInt[0, 100]

            @invariant
            def y_bounded(self):
                return self.y >= 0

            @transition
            def update(self, v: BoundedInt[1, 10]):
                require(self.x + v <= 100)
                self.x += v

        result = verify_spec(ChildSpec)
        assert result.passed


class TestNoRequireTransition:
    """Transition with zero require() clauses that still preserves invariants."""

    def test_safe_without_require(self):
        class SafeSpec(Spec):
            x: BoundedInt[0, 100]

            @invariant
            def non_negative(self):
                return self.x >= 0

            @transition
            def set_to_fifty(self, dummy: BoundedInt[0, 0]):
                self.x = 50  # Always safe

        result = verify_spec(SafeSpec)
        assert result.passed


class TestMultipleSpecsInFile:
    """Two different spec classes coexist."""

    def test_both_verify(self):
        class SpecA(Spec):
            a: BoundedInt[0, 100]

            @invariant
            def a_pos(self):
                return self.a >= 0

        class SpecB(Spec):
            b: BoundedInt[0, 100]

            @invariant
            def b_pos(self):
                return self.b >= 0

        assert verify_spec(SpecA).passed
        assert verify_spec(SpecB).passed


class TestBuiltinFieldNames:
    """Fields named after Python builtins."""

    def test_builtin_names_work(self):
        class BuiltinSpec(Spec):
            type: BoundedInt[0, 10]
            id: BoundedInt[0, 1000]
            max: BoundedInt[0, 100]

            @invariant
            def all_bounded(self):
                return And(self.type >= 0, self.id >= 0, self.max >= 0)

        fields = BuiltinSpec.state_fields()
        assert "type" in fields
        assert "id" in fields
        assert "max" in fields
        result = verify_spec(BuiltinSpec)
        assert result.passed


class TestFieldNotInSpec:
    """Invariant referencing an undefined field should error during verification."""

    def test_undefined_field_errors(self):
        class BadSpec(Spec):
            x: BoundedInt[0, 100]

            @invariant
            def bad(self):
                return self.y >= 0  # y is not defined

        result = verify_spec(BadSpec)
        # Should error (not pass silently)
        errors = [r for r in result.results if r.status == "error"]
        assert len(errors) >= 1
        assert "y" in (errors[0].error_message or "")


class TestParamFieldCollision:
    """Transition parameter name collides with state field name."""

    def test_collision_works(self):
        class CollisionSpec(Spec):
            x: BoundedInt[0, 100]

            @invariant
            def bounded(self):
                return self.x <= 100

            @transition
            def update(self, x: BoundedInt[1, 10]):
                # param 'x' collides with field 'x'
                require(self.x + x <= 100)
                self.x += x

        # Should still verify correctly — params are namespaced
        result = verify_spec(CollisionSpec)
        assert result.passed
