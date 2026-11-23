"""Component membership changes refresh only component_ids (#373)."""

from __future__ import annotations

from application.artifact.components import RefreshArtifactComponents
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ContextAssignment
from domain.knowledge import SourceReference


class _Index:
    def __init__(self, descriptor: ArtifactDescriptor) -> None:
        self.descriptor = descriptor
        self.upserts = 0

    def upsert(self, descriptor: ArtifactDescriptor) -> None:
        self.upserts += 1
        self.descriptor = descriptor

    def remove(self, reference: SourceReference) -> None: ...
    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        if reference == self.descriptor.reference:
            return self.descriptor
        return None

    def find_by_key(self, keys: tuple[str, ...]) -> tuple[ArtifactDescriptor, ...]:
        return ()

    def list_for_scope(
        self, *, source_type: str | None = None
    ) -> tuple[ArtifactDescriptor, ...]:
        return (self.descriptor,)


def test_path_prefix_move_updates_only_component_ids() -> None:
    reference = SourceReference("acme/proj:orders/cancel.py", "github")
    descriptor = ArtifactDescriptor(
        reference=reference,
        revision="sha",
        kind=ArtifactKind.CODE_FILE,
        contexts=(ContextAssignment("backend", "role_default"),),
        component_ids=("cmp_orders",),
        title="cancel.py",
    )
    index = _Index(descriptor)
    refresh = RefreshArtifactComponents(
        index,
        component_ids_for=lambda _ref: ("cmp_payments",),
    )

    refresh.execute(reference)

    assert index.descriptor.component_ids == ("cmp_payments",)
    assert index.descriptor.revision == "sha"
    assert index.descriptor.kind == ArtifactKind.CODE_FILE
    assert index.descriptor.contexts == descriptor.contexts
    assert index.upserts == 1
