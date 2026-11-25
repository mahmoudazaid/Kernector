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
    recorder.execute(_source("PROJ-140", "inst/PROJ:PROJ-140"), revision="r1")
    assert store.list_for_artifact("prj_orders", UnresolvedKey("PROJ-123")) == ()
