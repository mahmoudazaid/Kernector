"""RecordExplicitRelationships: upsert, unresolved resolve, watermark (#374)."""

from __future__ import annotations

from pathlib import Path

import pytest

from application.relationship.record import RecordExplicitRelationships
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ArtifactRef
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from domain.relationship.models import (
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
    ProviderLink,
    UnresolvedKey,
)
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.connectors.jira.link_extractor import (
    PROVIDER_LINKS_EXTRA_KEY,
    encode_provider_links,
)
from infrastructure.relationship.sql_store import SqlRelationshipStore


class _FixedExtractor:
    def __init__(self, links: tuple[ProviderLink, ...]) -> None:
        self._links = links

    def extract(self, document, raw):  # noqa: ANN001
        del document, raw
        return self._links


def _raw(_source_doc: SourceDocument) -> dict[str, object]:
    return {"v": 1, "issue_key": "x", "links": []}


def _descriptor(source_id: str, key: str) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=SourceReference(source_id, SourceType.JIRA),
        revision="r1",
        kind=ArtifactKind.TEST_CASE,
        external_keys=(key,),
        title=key,
    )


def _source(
    key: str,
    source_id: str,
    *,
    links: list[dict[str, str]] | None = None,
) -> SourceDocument:
    payload = {
        "v": 1,
        "issue_key": key,
        "links": links
        or [
            {
                "field": "issuelinks",
                "type_name": "Tests",
                "direction": "outward",
                "other_key": "PROJ-123",
            }
        ],
    }
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(source_id, SourceType.JIRA),
            title=key,
            provider="jira",
            content_format="markdown",
            extra={
                "jira_issue_key": key,
                "jira_instance_id": "inst",
                "jira_project_key": "PROJ",
                "jira_updated_at": "2026-10-01T12:00:00.000+0000",
                PROVIDER_LINKS_EXTRA_KEY: encode_provider_links(payload),
            },
        ),
        f"# {key}",
    )


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def index(path: Path) -> SqlArtifactIndex:
    return SqlArtifactIndex(path, "ws-a")


@pytest.fixture
def store(path: Path) -> SqlRelationshipStore:
    return SqlRelationshipStore(path, "ws-a")


def test_records_provider_link_under_resolved_projects(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={
            "jira": _FixedExtractor(
                (
                    ProviderLink(
                        relation_type="tests",
                        subject_key="PROJ-140",
                        object_key="PROJ-123",
                        locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
                    ),
                )
            )
        },
        raw_from_document=_raw,
    )
    source = _source("PROJ-140", "inst/PROJ:PROJ-140")

    recorder.execute(source, revision="2026-10-01T12:00:00.000+0000")

    listed = store.list_for_artifact(
        "prj_orders", ArtifactRef(SourceReference("inst/PROJ:PROJ-123", "jira"))
    )
    assert len(listed) == 1
    assert listed[0].origin == ORIGIN_PROVIDER_DECLARED
    assert listed[0].relation_type == "tests"
    assert store.get_record_watermark(source.reference) is not None


def test_unresolved_object_resolves_when_target_arrives(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={
            "jira": _FixedExtractor(
                (
                    ProviderLink(
                        relation_type="tests",
                        subject_key="PROJ-140",
                        object_key="PROJ-123",
                        locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
                    ),
                )
            )
        },
        raw_from_document=_raw,
    )
    recorder.execute(
        _source("PROJ-140", "inst/PROJ:PROJ-140"),
        revision="r1",
    )
    pending = store.list_for_artifact(
        "prj_orders", UnresolvedKey("PROJ-123"), aliases=("PROJ-123",)
    )
    assert len(pending) == 1
    assert isinstance(pending[0].object, UnresolvedKey)

    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    inward_recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={
            "jira": _FixedExtractor(
                (
                    ProviderLink(
                        relation_type="tests",
                        subject_key="PROJ-140",
                        object_key="PROJ-123",
                        locator="field=issuelinks;type=Tests;dir=in;key=PROJ-140",
                    ),
                )
            )
        },
        raw_from_document=_raw,
    )
    inward_recorder.execute(
        _source(
            "PROJ-123",
            "inst/PROJ:PROJ-123",
            links=[
                {
                    "field": "issuelinks",
                    "type_name": "Tests",
                    "direction": "inward",
                    "other_key": "PROJ-140",
                }
            ],
        ),
        revision="r2",
    )

    listed = store.list_for_artifact(
        "prj_orders", ArtifactRef(SourceReference("inst/PROJ:PROJ-123", "jira"))
    )
    assert len(listed) == 1
    assert isinstance(listed[0].object, ArtifactRef)
    assert len(listed[0].evidence) == 2


def test_idempotent_when_watermark_matches(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    extractor = _FixedExtractor(
        (
            ProviderLink(
                relation_type="tests",
                subject_key="PROJ-140",
                object_key="PROJ-123",
                locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
            ),
        )
    )
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={"jira": extractor},
        raw_from_document=_raw,
    )
    source = _source("PROJ-140", "inst/PROJ:PROJ-140")
    recorder.execute(source, revision="r1")
    recorder.execute(source, revision="r1")

    listed = store.list_for_artifact(
        "prj_orders", ArtifactRef(SourceReference("inst/PROJ:PROJ-140", "jira"))
    )
    assert len(listed) == 1
    assert len(listed[0].evidence) == 1


def test_skips_when_source_has_no_project(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: (),
        extractors={
            "jira": _FixedExtractor(
                (
                    ProviderLink(
                        relation_type="tests",
                        subject_key="PROJ-140",
                        object_key="PROJ-123",
                        locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
                    ),
                )
            )
        },
        raw_from_document=_raw,
    )
    source = _source("PROJ-140", "inst/PROJ:PROJ-140")
    recorder.execute(source, revision="r1")
    assert store.list_for_artifact("prj_orders", UnresolvedKey("PROJ-123")) == ()
    assert store.get_record_watermark(source.reference) is None
    assert recorder.needs_retry(source.reference, revision="r1") is False
    assert recorder.needs_retry(
        source.reference, revision="r1", links_fingerprint="changed"
    ) is False


def test_records_after_project_association(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    projects: dict[str, tuple[str, ...]] = {"ids": ()}
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: projects["ids"],
        extractors={
            "jira": _FixedExtractor(
                (
                    ProviderLink(
                        relation_type="tests",
                        subject_key="PROJ-140",
                        object_key="PROJ-123",
                        locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
                    ),
                )
            )
        },
        raw_from_document=_raw,
    )
    source = _source("PROJ-140", "inst/PROJ:PROJ-140")
    recorder.execute(source, revision="r1")
    assert store.get_record_watermark(source.reference) is None

    projects["ids"] = ("prj_orders",)
    assert recorder.needs_retry(source.reference, revision="r1") is True
    recorder.execute(source, revision="r1")

    listed = store.list_for_artifact(
        "prj_orders", ArtifactRef(SourceReference("inst/PROJ:PROJ-123", "jira"))
    )
    assert len(listed) == 1


def test_needs_retry_when_revision_advances(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    index.upsert(_descriptor("inst/PROJ:PROJ-123", "PROJ-123"))
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={
            "jira": _FixedExtractor(
                (
                    ProviderLink(
                        relation_type="tests",
                        subject_key="PROJ-140",
                        object_key="PROJ-123",
                        locator="field=issuelinks;type=Tests;dir=out;key=PROJ-123",
                    ),
                )
            )
        },
        raw_from_document=_raw,
    )
    source = _source("PROJ-140", "inst/PROJ:PROJ-140")
    recorder.execute(source, revision="r1")
    assert recorder.needs_retry(source.reference, revision="r1") is False
    assert recorder.needs_retry(source.reference, revision="r2") is True


def test_keeps_unresolved_when_only_other_instance_matches(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("old-instance/PROJ:PROJ-123", "PROJ-123"))
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={
            "jira": _FixedExtractor(
                (
                    ProviderLink(
                        relation_type="blocks",
                        subject_key="PROJ-100",
                        object_key="PROJ-123",
                        locator="field=issuelinks;type=Blocks;dir=out;key=PROJ-123",
                    ),
                )
            )
        },
        raw_from_document=_raw,
    )
    index.upsert(_descriptor("new-instance/PROJ:PROJ-100", "PROJ-100"))
    recorder.execute(
        _source("PROJ-100", "new-instance/PROJ:PROJ-100"),
        revision="r1",
    )
    listed = store.list_for_artifact(
        "prj_orders",
        ArtifactRef(SourceReference("new-instance/PROJ:PROJ-100", "jira")),
    )
    assert len(listed) == 1
    assert isinstance(listed[0].object, UnresolvedKey)
    assert listed[0].object.key == "PROJ-123"


def test_resolve_arriving_preserves_confirmed_inferred_edge(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    from datetime import datetime, timezone

    from domain.relationship.models import ORIGIN_INFERRED, VERIFICATION_UNVERIFIED

    edge = store.upsert_from_evidence(
        project_id="prj_orders",
        subject=ArtifactRef(SourceReference("inst/PROJ:PROJ-140", "jira")),
        relation_type="relates_to",
        object=UnresolvedKey("PROJ-9"),
        origin=ORIGIN_INFERRED,
        verification=VERIFICATION_UNVERIFIED,
        confidence=0.4,
        freshness="current",
        evidence=EvidenceRef(
            source=SourceReference("inst/PROJ:PROJ-140", "jira"),
            revision="r1",
            locator="field=model;span=1",
            extractor_id="inferred",
        ),
        seen_at="2026-10-01T12:00:00Z",
    )
    store.apply_decision(
        edge.relationship_id,
        verification=VERIFICATION_VERIFIED,
        actor="operator",
        at=datetime(2026, 11, 24, 12, 0, tzinfo=timezone.utc),
        expected_version=edge.decision_version,
    )
    index.upsert(_descriptor("inst/PROJ:PROJ-9", "PROJ-9"))
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={"jira": _FixedExtractor(())},
        raw_from_document=_raw,
    )
    recorder.resolve_arriving(_source("PROJ-9", "inst/PROJ:PROJ-9"))
    loaded = store.get(edge.relationship_id)
    assert loaded is not None
    assert isinstance(loaded.object, ArtifactRef)
    assert loaded.object.reference.source_id == "inst/PROJ:PROJ-9"
    assert loaded.origin == ORIGIN_INFERRED
    assert loaded.verification == VERIFICATION_VERIFIED
    assert loaded.decision_actor == "operator"


def test_needs_retry_ignores_other_instance_unresolved(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst-b/PROJ:PROJ-9", "PROJ-9"))
    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=ArtifactRef(SourceReference("inst-a/PROJ:PROJ-1", "jira")),
        relation_type="relates_to",
        object=UnresolvedKey("PROJ-9"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=SourceReference("inst-a/PROJ:PROJ-1", "jira"),
            revision="r1",
            locator="field=issuelinks;type=Relates;dir=out;key=PROJ-9",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-10-01T12:00:00Z",
    )
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={"jira": _FixedExtractor(())},
        raw_from_document=_raw,
        mapping_fingerprint="m1",
    )
    store.set_record_watermark(
        SourceReference("inst-b/PROJ:PROJ-9", "jira"),
        "v2\nfp\nr1\nprj_orders\nm1",
    )
    assert (
        recorder.needs_retry(
            SourceReference("inst-b/PROJ:PROJ-9", "jira"), revision="r1"
        )
        is False
    )


def test_resolve_arriving_skips_unsupported_sources(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    # Same instance prefix as the evidence so the instance check would otherwise
    # allow resolution; supports() must still short-circuit.
    github_ref = SourceReference("inst/repo:openapi.yaml", "github")
    index.upsert(
        ArtifactDescriptor(
            reference=github_ref,
            revision="r1",
            kind=ArtifactKind.API_SPEC,
            external_keys=("openapi",),
            title="openapi",
        )
    )
    store.upsert_from_evidence(
        project_id="prj_orders",
        subject=ArtifactRef(SourceReference("inst/PROJ:PROJ-140", "jira")),
        relation_type="tests",
        object=UnresolvedKey("openapi"),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=SourceReference("inst/PROJ:PROJ-140", "jira"),
            revision="r1",
            locator="field=issuelinks;type=Tests;dir=out;key=openapi",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-10-01T12:00:00Z",
    )
    lookups: list[str] = []
    original = store.list_unresolved_for_key

    def _tracking_list(key: str, *, part_key: str | None = None):
        lookups.append(key)
        return original(key, part_key=part_key)

    store.list_unresolved_for_key = _tracking_list  # type: ignore[method-assign]
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: (),
        extractors={"jira": _FixedExtractor(())},
        raw_from_document=_raw,
    )
    source = SourceDocument(
        SourceMetadata(
            reference=github_ref,
            title="openapi",
            provider="github",
            content_format="json",
            extra={},
        ),
        "{}",
    )
    recorder.resolve_arriving(source)
    assert lookups == []
    pending = original("openapi")
    assert len(pending) == 1
    assert isinstance(pending[0].object, UnresolvedKey)


def test_preserves_part_key_on_resolved_endpoint(
    index: SqlArtifactIndex, store: SqlRelationshipStore
) -> None:
    index.upsert(_descriptor("inst/api:openapi", "openapi"))
    recorder = RecordExplicitRelationships(
        store,
        index,
        project_ids_for=lambda _ref: ("prj_orders",),
        extractors={
            "jira": _FixedExtractor(
                (
                    ProviderLink(
                        relation_type="tests",
                        subject_key="PROJ-140",
                        object_key="openapi",
                        locator="field=issuelinks;type=Tests;dir=out;key=openapi",
                        object_part_key="GET /orders",
                    ),
                )
            )
        },
        raw_from_document=_raw,
    )
    index.upsert(_descriptor("inst/PROJ:PROJ-140", "PROJ-140"))
    recorder.execute(_source("PROJ-140", "inst/PROJ:PROJ-140"), revision="r1")
    listed = store.list_for_artifact(
        "prj_orders",
        ArtifactRef(
            SourceReference("inst/api:openapi", "jira"),
            part_key="GET /orders",
        ),
    )
    assert len(listed) == 1
    assert isinstance(listed[0].object, ArtifactRef)
    assert listed[0].object.part_key == "GET /orders"
