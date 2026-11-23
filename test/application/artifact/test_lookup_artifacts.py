"""LookupArtifacts: exact keys, project scope, live project_ids (#373)."""

from __future__ import annotations

from datetime import UTC, datetime

from application.artifact.lookup import LookupArtifacts
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ArtifactPart, ContextAssignment
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceReference,
)
from test.document_doubles import InMemoryDocumentCatalog


class _Index:
    def __init__(self, *descriptors: ArtifactDescriptor) -> None:
        self._by_ref = {
            (d.reference.source_type, d.reference.source_id): d for d in descriptors
        }
        self._by_key: dict[str, list[ArtifactDescriptor]] = {}
        for descriptor in descriptors:
            for key in descriptor.external_keys:
                self._by_key.setdefault(key, []).append(descriptor)

    def upsert(self, descriptor: ArtifactDescriptor) -> None:
        self._by_ref[
            (descriptor.reference.source_type, descriptor.reference.source_id)
        ] = descriptor

    def remove(self, reference: SourceReference) -> None:
        self._by_ref.pop((reference.source_type, reference.source_id), None)

    def get(self, reference: SourceReference) -> ArtifactDescriptor | None:
        return self._by_ref.get((reference.source_type, reference.source_id))

    def find_by_key(self, keys: tuple[str, ...]) -> tuple[ArtifactDescriptor, ...]:
        found: list[ArtifactDescriptor] = []
        seen: set[tuple[str, str]] = set()
        for key in keys:
            for descriptor in self._by_key.get(key, ()):
                ref = (
                    descriptor.reference.source_type,
                    descriptor.reference.source_id,
                )
                if ref not in seen:
                    seen.add(ref)
                    found.append(descriptor)
        return tuple(found)

    def list_for_scope(
        self, *, source_type: str | None = None
    ) -> tuple[ArtifactDescriptor, ...]:
        return tuple(self._by_ref.values())


NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _catalog_row(reference: SourceReference, revision: str = "r1") -> CatalogDocument:
    return CatalogDocument(
        reference=reference,
        file_name="issue.md",
        title="story",
        content_format="markdown",
        status=CatalogStatus.READY,
        created_at=NOW,
        updated_at=NOW,
        chunk_count=1,
        error=None,
        revision=revision,
    )


def _story(
    key: str = "PROJ-123",
    source_id: str = "cloud/PROJ:PROJ-123",
) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=SourceReference(source_id, "jira"),
        revision="r1",
        kind=ArtifactKind.STORY,
        contexts=(ContextAssignment("business", "role_default"),),
        external_keys=(key,),
        title=f"{key} story",
    )


def test_lookup_returns_descriptor_and_current_catalog_document() -> None:
    story = _story()
    catalog = InMemoryDocumentCatalog()
    catalog.upsert(_catalog_row(story.reference, revision="r1"))
    lookup = LookupArtifacts(
        _Index(story),
        catalog,
        project_ids_for=lambda _ref: ("prj_proj",),
    )

    matches = lookup.execute(("PROJ-123",), project_id="prj_proj")

    assert len(matches) == 1
    assert matches[0].descriptor == story
    assert matches[0].document is not None
    assert matches[0].document.revision == "r1"
    assert matches[0].project_ids == ("prj_proj",)


def test_pay_key_excluded_for_proj_project() -> None:
    pay = _story(key="PAY-123", source_id="cloud/PAY:PAY-123")
    lookup = LookupArtifacts(
        _Index(pay),
        InMemoryDocumentCatalog(),
        project_ids_for=lambda _ref: ("prj_pay",),
    )

    assert lookup.execute(("PAY-123",), project_id="prj_proj") == ()


def test_workspace_lookup_reports_multi_project_ids() -> None:
    story = _story()
    lookup = LookupArtifacts(
        _Index(story),
        InMemoryDocumentCatalog(),
        project_ids_for=lambda _ref: ("prj_a", "prj_b"),
    )

    matches = lookup.execute(("PROJ-123",))

    assert matches[0].project_ids == ("prj_a", "prj_b")


def test_unassociated_source_has_empty_project_ids() -> None:
    story = _story()
    lookup = LookupArtifacts(
        _Index(story),
        InMemoryDocumentCatalog(),
        project_ids_for=lambda _ref: (),
    )

    matches = lookup.execute(("PROJ-123",))

    assert matches[0].project_ids == ()


def test_suggested_and_rejected_do_not_appear_in_project_ids() -> None:
    """project_ids_for is ResolveProjectsForSource: confirmed only."""
    story = _story()
    # Simulate resolver that already excludes suggested/rejected.
    lookup = LookupArtifacts(
        _Index(story),
        InMemoryDocumentCatalog(),
        project_ids_for=lambda _ref: (),
    )

    matches = lookup.execute(("PROJ-123",))

    assert matches[0].project_ids == ()
    assert lookup.execute(("PROJ-123",), project_id="prj_suggested") == ()


def test_part_key_and_operation_id_resolve_same_part() -> None:
    part = ArtifactPart(
        kind="api_operation",
        part_key="POST /orders/{orderId}/cancel",
        operation_id="cancelOrder",
        summary="Cancel",
        response_codes=("200",),
    )
    spec = ArtifactDescriptor(
        reference=SourceReference("acme/proj:api/openapi.yaml", "github"),
        revision="sha",
        kind=ArtifactKind.API_SPEC,
        contexts=(ContextAssignment("api_contract", "rule_openapi"),),
        external_keys=("cancelOrder", "POST /orders/{orderId}/cancel"),
        parts=(part,),
        title="openapi.yaml",
    )
    lookup = LookupArtifacts(
        _Index(spec),
        InMemoryDocumentCatalog(),
        project_ids_for=lambda _ref: ("prj_proj",),
    )

    by_id = lookup.execute(("cancelOrder",), project_id="prj_proj")
    by_path = lookup.execute(
        ("POST /orders/{orderId}/cancel",), project_id="prj_proj"
    )

    assert by_id[0].part == part
    assert by_path[0].part == part
    assert by_id[0].descriptor.reference == by_path[0].descriptor.reference
