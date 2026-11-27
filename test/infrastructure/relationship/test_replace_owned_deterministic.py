"""Owned deterministic evidence replace and watermark kinds (#375)."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.artifact.models import ArtifactRef
from domain.knowledge import SourceReference
from domain.relationship.models import (
    ORIGIN_DETERMINISTIC,
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
)
from domain.relationship.ports import (
    WATERMARK_KIND_DETERMINISTIC,
    WATERMARK_KIND_PROVIDER_DECLARED,
    DeterministicEdgeWrite,
)
from infrastructure.catalog import _connection
from infrastructure.catalog.sql_schema import apply_migrations, current_schema_version
from infrastructure.relationship.sql_store import SqlRelationshipStore


def _ref(source_id: str, source_type: str = "github") -> ArtifactRef:
    return ArtifactRef(SourceReference(source_id, source_type))


def _det_evidence(
    source_id: str,
    *,
    revision: str,
    locator: str,
    rule_id: str = "key_mention.tag",
) -> EvidenceRef:
    return EvidenceRef(
        source=SourceReference(source_id, "github"),
        revision=revision,
        locator=locator,
        extractor_id=rule_id,
    )


@pytest.fixture
def store(tmp_path: Path) -> SqlRelationshipStore:
    return SqlRelationshipStore(tmp_path / "catalog.sqlite", "ws-a")


def test_migration_preserves_provider_watermarks_as_kind(
    tmp_path: Path,
) -> None:
    shipped = (
        Path(__file__).resolve().parents[3]
        / "infrastructure"
        / "catalog"
        / "migrations"
    )
    staged = tmp_path / "migrations"
    staged.mkdir()
    for path in sorted(shipped.glob("*.sql")):
        if path.name.startswith("012_"):
            continue
        (staged / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    db = tmp_path / "catalog.sqlite"
    apply_migrations(db, migrations_dir=staged)
    assert current_schema_version(db) == 11

    connection = _connection.connect(db)
    try:
        connection.execute(
            """
            INSERT INTO relationship_record_watermarks (
                workspace_id, source_type, source_id, links_fingerprint, recorded_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            ("ws-a", "jira", "inst/PROJ:1", "fp-old", "2026-01-01T00:00:00Z"),
        )
        connection.commit()
    finally:
        connection.close()

    apply_migrations(db)
    assert current_schema_version(db) == 12
    store = SqlRelationshipStore(db, "ws-a")
    assert (
        store.get_record_watermark(
            SourceReference("inst/PROJ:1", "jira"),
            kind=WATERMARK_KIND_PROVIDER_DECLARED,
        )
        == "fp-old"
    )
    assert (
        store.get_record_watermark(
            SourceReference("inst/PROJ:1", "jira"),
            kind=WATERMARK_KIND_DETERMINISTIC,
        )
        is None
    )


def test_replace_writes_automates_and_sets_deterministic_watermark(
    store: SqlRelationshipStore,
) -> None:
    source_id = "gh/acme/proj-tests:tests/orders/cancel_order.robot"
    source = SourceReference(source_id, "github")
    store.replace_owned_deterministic_evidence(
        source=source,
        revision="rev1",
        owned_rule_ids=frozenset({"key_mention.tag"}),
        edges=(
            DeterministicEdgeWrite(
                project_id="prj_orders",
                subject=_ref(source_id),
                relation_type="automates",
                object=_ref("inst/PROJ:PROJ-123", "jira"),
                evidence=_det_evidence(source_id, revision="rev1", locator="line=6"),
            ),
            DeterministicEdgeWrite(
                project_id="prj_orders",
                subject=_ref(source_id),
                relation_type="automates",
                object=_ref("inst/PROJ:PROJ-140", "jira"),
                evidence=_det_evidence(
                    source_id, revision="rev1", locator="line=6;key=PROJ-140"
                ),
            ),
        ),
        watermark="wm-1",
        seen_at="2026-11-26T12:00:00Z",
    )

    listed = store.list_for_artifact("prj_orders", _ref(source_id))
    assert len(listed) == 2
    assert all(edge.origin == ORIGIN_DETERMINISTIC for edge in listed)
    assert all(edge.verification == VERIFICATION_VERIFIED for edge in listed)
    assert all(
        edge.evidence[0].extractor_id == "key_mention.tag" for edge in listed
    )
    assert (
        store.get_record_watermark(source, kind=WATERMARK_KIND_DETERMINISTIC) == "wm-1"
    )


def test_replace_preserves_provider_evidence_and_origin(
    store: SqlRelationshipStore,
) -> None:
    source_id = "gh/acme/proj-tests:tests/orders/cancel_order.robot"
    source = SourceReference(source_id, "github")
    jira_subject = _ref("inst/PROJ:PROJ-140", "jira")
    jira_object = _ref("inst/PROJ:PROJ-123", "jira")
    provider = store.upsert_from_evidence(
        project_id="prj_orders",
        subject=jira_subject,
        relation_type="automates",
        object=jira_object,
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=SourceReference("inst/PROJ:PROJ-140", "jira"),
            revision="jira-1",
            locator="field=issuelinks",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-11-26T11:00:00Z",
    )

    store.replace_owned_deterministic_evidence(
        source=source,
        revision="rev1",
        owned_rule_ids=frozenset({"key_mention.tag"}),
        edges=(
            DeterministicEdgeWrite(
                project_id="prj_orders",
                subject=_ref(source_id),
                relation_type="automates",
                object=jira_object,
                evidence=_det_evidence(source_id, revision="rev1", locator="line=6"),
                subject_aliases=(),
            ),
        ),
        watermark="wm-1",
        seen_at="2026-11-26T12:00:00Z",
    )

    # Different subject token → separate edge; provider edge untouched.
    loaded = store.get(provider.relationship_id)
    assert loaded is not None
    assert loaded.origin == ORIGIN_PROVIDER_DECLARED
    assert len(loaded.evidence) == 1
    assert loaded.evidence[0].extractor_id == "jira_explicit_links"


def test_disappeared_owned_only_edge_marked_removed_retains_evidence(
    store: SqlRelationshipStore,
) -> None:
    source_id = "gh/file.robot"
    source = SourceReference(source_id, "github")
    store.replace_owned_deterministic_evidence(
        source=source,
        revision="rev1",
        owned_rule_ids=frozenset({"key_mention.tag"}),
        edges=(
            DeterministicEdgeWrite(
                project_id="prj_orders",
                subject=_ref(source_id),
                relation_type="automates",
                object=_ref("inst/PROJ:PROJ-123", "jira"),
                evidence=_det_evidence(source_id, revision="rev1", locator="line=1"),
            ),
        ),
        watermark="wm-1",
        seen_at="2026-11-26T12:00:00Z",
    )
    listed = store.list_for_artifact("prj_orders", _ref(source_id))
    assert len(listed) == 1
    edge_id = listed[0].relationship_id

    store.replace_owned_deterministic_evidence(
        source=source,
        revision="rev2",
        owned_rule_ids=frozenset({"key_mention.tag"}),
        edges=(),
        watermark="wm-2",
        seen_at="2026-11-26T13:00:00Z",
    )
    loaded = store.get(edge_id)
    assert loaded is not None
    assert loaded.freshness == "removed"
    assert len(loaded.evidence) == 1
    assert loaded.evidence[0].revision == "rev1"


def test_clear_watermark_all_kinds(store: SqlRelationshipStore) -> None:
    source = SourceReference("gh/file.robot", "github")
    store.set_record_watermark(source, "p", kind=WATERMARK_KIND_PROVIDER_DECLARED)
    store.set_record_watermark(source, "d", kind=WATERMARK_KIND_DETERMINISTIC)
    store.clear_record_watermark(source)
    assert store.get_record_watermark(source, kind=WATERMARK_KIND_PROVIDER_DECLARED) is None
    assert store.get_record_watermark(source, kind=WATERMARK_KIND_DETERMINISTIC) is None


def test_mark_owned_deterministic_stale_keeps_evidence(
    store: SqlRelationshipStore,
) -> None:
    source_id = "gh/file.robot"
    source = SourceReference(source_id, "github")
    store.replace_owned_deterministic_evidence(
        source=source,
        revision="rev1",
        owned_rule_ids=frozenset({"key_mention.tag"}),
        edges=(
            DeterministicEdgeWrite(
                project_id="prj_orders",
                subject=_ref(source_id),
                relation_type="automates",
                object=_ref("inst/PROJ:PROJ-123", "jira"),
                evidence=_det_evidence(source_id, revision="rev1", locator="line=1"),
            ),
        ),
        watermark="wm-1",
        seen_at="2026-11-26T12:00:00Z",
    )
    store.mark_owned_deterministic_stale(
        source=source,
        owned_rule_ids=frozenset({"key_mention.tag"}),
        watermark="wm-bound",
    )
    listed = store.list_for_artifact("prj_orders", _ref(source_id))
    assert listed[0].freshness == "stale"
    assert len(listed[0].evidence) == 1
    assert (
        store.get_record_watermark(source, kind=WATERMARK_KIND_DETERMINISTIC)
        == "wm-bound"
    )
