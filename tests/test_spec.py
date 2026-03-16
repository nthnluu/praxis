"""Tests for praxis.spec — Spec base class."""

from praxis import Spec, invariant, transition, verify, And
from praxis.types import BoundedInt, BoundedFloat, Bool


class TestSpecCollection:
    def test_state_fields(self):
        class MySpec(Spec):
            x: BoundedInt[0, 100]
            y: BoundedFloat[0.0, 1.0]
            flag: Bool

        fields = MySpec.state_fields()
        assert set(fields.keys()) == {"x", "y", "flag"}

    def test_invariants_collected(self):
        class MySpec(Spec):
            x: BoundedInt[0, 100]

            @invariant
            def pos(self):
                return self.x >= 0

            @invariant
            def bounded(self):
                return self.x <= 100

        invs = MySpec.invariants()
        assert len(invs) == 2
        assert {m.__name__ for m in invs} == {"pos", "bounded"}

    def test_transitions_collected(self):
        class MySpec(Spec):
            x: BoundedInt[0, 100]

            @transition
            def update(self, delta: BoundedInt[-10, 10]):
                self.x += delta

        trans = MySpec.transitions()
        assert len(trans) == 1
        assert trans[0].__name__ == "update"

    def test_verifications_collected(self):
        class MySpec(Spec):
            x: BoundedInt[0, 100]

            @verify(target="some.func")
            def check_func(self):
                pass

        assert len(MySpec.verifications()) == 1

    def test_non_praxis_annotations_ignored(self):
        class MySpec(Spec):
            x: BoundedInt[0, 100]
            name: str

        fields = MySpec.state_fields()
        assert "x" in fields
        assert "name" not in fields

    def test_full_spec(self):
        class GPUSpec(Spec):
            vram_total: BoundedInt[1, 640]
            vram_used: BoundedInt[0, 640]

            @invariant
            def no_overcommit(self):
                return self.vram_used <= self.vram_total

            @transition
            def schedule_job(self, job_vram: BoundedInt[1, 80]):
                self.vram_used += job_vram

        assert len(GPUSpec.state_fields()) == 2
        assert len(GPUSpec.invariants()) == 1
        assert len(GPUSpec.transitions()) == 1
