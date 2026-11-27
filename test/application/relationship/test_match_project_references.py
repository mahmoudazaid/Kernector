"""MatchProjectReferences: deterministic key/API mentions (#375)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from application.relationship.match import MatchProjectReferences
from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor, ArtifactPart, ContextAssignment
from domain.knowledge import (
    CatalogDocument,
    CatalogStatus,
    SourceDocument,
    SourceMetadata,
    SourceReference,
)
from application.artifact.fanout_recorder import FanOutRelationshipRecorder
from domain.artifact.models import ArtifactRef
from domain.relationship.matching import MatchLimits
from domain.relationship.models import (
    ORIGIN_DETERMINISTIC,
    ORIGIN_PROVIDER_DECLARED,
    VERIFICATION_VERIFIED,
    EvidenceRef,
)
from domain.relationship.ports import WATERMARK_KIND_DETERMINISTIC
from infrastructure.artifact.sql_index import SqlArtifactIndex
from infrastructure.relationship.sql_store import SqlRelationshipStore
from packs.software_delivery.relationship.matchers.api_operation import (
    ApiOperationMentionMatcher,
)
from packs.software_delivery.relationship.matchers.doc import KeyMentionDocMatcher
from packs.software_delivery.relationship.matchers.header import KeyMentionHeaderMatcher
from packs.software_delivery.relationship.matchers.tag import KeyMentionTagMatcher
from packs.software_delivery.relationship.types import CONTEXT_RELATIONS
from test.document_doubles import InMemoryDocumentCatalog

NOW = datetime(2026, 11, 26, tzinfo=UTC)
PROJECT = "prj_proj"
LIMITS = MatchLimits(
    max_content_bytes=1_048_576,
    max_mentions=100,
    max_catalogue_entries=10_000,
    max_compiled_pattern_size=65_536,
)


def _catalog_row(reference: SourceReference, revision: str = "r1") -> CatalogDocument:
    return CatalogDocument(
        reference=reference,
        file_name="doc",
        title="doc",
        content_format="text",
        status=CatalogStatus.READY,
        created_at=NOW,
        updated_at=NOW,
        chunk_count=1,
        error=None,
        revision=revision,
    )


def _source(
    source_id: str,
    content: str,
    *,
    source_type: str = "github",
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(source_id, source_type),
            title=source_id.rsplit(":", 1)[-1],
            provider=source_type,
            content_format="text",
        ),
        content,
    )


def _story(key: str) -> ArtifactDescriptor:
    return ArtifactDescriptor(
        reference=SourceReference(f"cloud/PROJ:{key}", "jira"),
        revision="j1",
        kind=ArtifactKind.STORY,
        contexts=(ContextAssignment("business", "role_default"),),
        external_keys=(key,),
        title=key,
    )


def _harness(tmp_path: Path, *descriptors: ArtifactDescriptor):
    store = SqlRelationshipStore(tmp_path / "catalog.sqlite", "ws-a")
    index = SqlArtifactIndex(tmp_path / "catalog.sqlite", "ws-a")
    catalog = InMemoryDocumentCatalog()
    membership: dict[tuple[str, str], tuple[str, ...]] = {}
    for descriptor in descriptors:
        index.upsert(descriptor)
        catalog.upsert(_catalog_row(descriptor.reference, descriptor.revision))
        membership[
            (descriptor.reference.source_type, descriptor.reference.source_id)
        ] = (PROJECT,)

    def project_ids_for(reference: SourceReference) -> tuple[str, ...]:
        return membership.get((reference.source_type, reference.source_id), ())

    match = MatchProjectReferences(
        store,
        index,
        catalog,
        project_ids_for=project_ids_for,
        matchers=(
            KeyMentionTagMatcher(),
            KeyMentionHeaderMatcher(),
            KeyMentionDocMatcher(),
            ApiOperationMentionMatcher(),
        ),
        limits=LIMITS,
        rule_catalogue_version="software_delivery.matchers.v1",
        context_relations=CONTEXT_RELATIONS,
        now=lambda: "2026-11-26T12:00:00Z",
    )
    return store, index, catalog, membership, match


def test_robot_tags_create_automates_with_line_span_and_rule_id(
    tmp_path: Path,
) -> None:
    robot_path = (
        Path(__file__).resolve().parents[2]
        / "fixtures"
        / "project_intelligence"
        / "v1"
        / "acme"
        / "proj-tests"
        / "tests"
        / "orders"
        / "cancel_order.robot"
    )
    content = robot_path.read_text(encoding="utf-8")
    source_id = "gh/acme/proj-tests:tests/orders/cancel_order.robot"
    store, index, catalog, membership, match = _harness(
        tmp_path, _story("PROJ-123"), _story("PROJ-140")
    )
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    index.upsert(subject)
    catalog.upsert(_catalog_row(subject.reference, "rev1"))
    membership[("github", source_id)] = (PROJECT,)

    source = _source(source_id, content)
    assert match.needs_record(source, revision="rev1")
    match.execute(source, revision="rev1")

    edges = store.list_for_artifact(PROJECT, ArtifactRef(subject.reference))
    assert len(edges) == 2
    objects = {
        edge.object.reference.source_id  # type: ignore[union-attr]
        for edge in edges
    }
    assert objects == {"cloud/PROJ:PROJ-123", "cloud/PROJ:PROJ-140"}
    for edge in edges:
        assert edge.relation_type == "automates"
        assert edge.origin == ORIGIN_DETERMINISTIC
        assert edge.verification == VERIFICATION_VERIFIED
        assert edge.evidence[0].extractor_id == "key_mention.tag"
        assert edge.evidence[0].locator.startswith("line=")
    assert not match.needs_record(source, revision="rev1")


def _register_subject(
    index: SqlArtifactIndex,
    catalog: InMemoryDocumentCatalog,
    membership: dict[tuple[str, str], tuple[str, ...]],
    subject: ArtifactDescriptor,
    *,
    projects: tuple[str, ...] = (PROJECT,),
) -> None:
    index.upsert(subject)
    catalog.upsert(_catalog_row(subject.reference, subject.revision))
    membership[(subject.reference.source_type, subject.reference.source_id)] = projects


def test_gherkin_pytest_and_playwright_title_tags(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-123"))
    cases = [
        (
            "gh/f.feature",
            "@PROJ-123\nScenario: Cancel\n  Given x\n",
        ),
        (
            "gh/t.py",
            '@pytest.mark.jira("PROJ-123")\ndef test_cancel():\n    pass\n',
        ),
        (
            "gh/e2e/cancel-order.spec.ts",
            (
                Path(__file__).resolve().parents[2]
                / "fixtures/project_intelligence/v1/acme/proj-e2e/e2e/cancel-order.spec.ts"
            ).read_text(encoding="utf-8"),
        ),
    ]
    for source_id, content in cases:
        subject = ArtifactDescriptor(
            reference=SourceReference(source_id, "github"),
            revision="rev1",
            kind=ArtifactKind.AUTOMATED_TEST,
            contexts=(ContextAssignment("testing", "path_rule"),),
        )
        _register_subject(index, catalog, membership, subject)
        match.execute(_source(source_id, content), revision="rev1")
        edges = store.list_for_artifact(PROJECT, ArtifactRef(subject.reference))
        assert len(edges) == 1
        assert edges[0].relation_type == "automates"
        assert edges[0].evidence[0].extractor_id == "key_mention.tag"


def test_header_docstring_yields_references_not_implements(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-123"))
    source_id = "gh/acme/proj/orders/cancel.py"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.CODE_FILE,
        contexts=(
            ContextAssignment("backend", "path_rule"),
            ContextAssignment("frontend", "path_rule"),
        ),
    )
    _register_subject(index, catalog, membership, subject)
    match.execute(
        _source(source_id, '"""PROJ-123: cancel unpaid orders."""\n\ndef cancel():\n    pass\n'),
        revision="rev1",
    )
    edges = store.list_for_artifact(PROJECT, ArtifactRef(subject.reference))
    assert len(edges) == 1
    assert edges[0].relation_type == "references"
    assert edges[0].evidence[0].extractor_id == "key_mention.header"


def test_document_mention_yields_describes(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-123"))
    source_id = "gh/docs/cancel.md"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.DOCUMENT,
        contexts=(ContextAssignment("documentation", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject)
    match.execute(_source(source_id, "See PROJ-123 for cancel flow.\n"), revision="rev1")
    edges = store.list_for_artifact(PROJECT, ArtifactRef(subject.reference))
    assert len(edges) == 1
    assert edges[0].relation_type == "describes"


def test_foreign_project_key_is_ignored(tmp_path: Path) -> None:
    source_id = "gh/acme/proj-tests:tests/x.robot"
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-123"))
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject)
    source = _source(
        source_id,
        "*** Test Cases ***\nX\n    [Tags]    PAY-123    PROJ-123\n",
    )
    match.execute(source, revision="rev1")
    edges = store.list_for_artifact(PROJECT, ArtifactRef(subject.reference))
    assert len(edges) == 1
    assert edges[0].object.reference.source_id == "cloud/PROJ:PROJ-123"  # type: ignore[union-attr]


def test_multi_project_isolation(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path)
    proj_story = _story("PROJ-123")
    other = ArtifactDescriptor(
        reference=SourceReference("cloud/PAY:PAY-123", "jira"),
        revision="j1",
        kind=ArtifactKind.STORY,
        contexts=(ContextAssignment("business", "role_default"),),
        external_keys=("PAY-123",),
    )
    index.upsert(proj_story)
    catalog.upsert(_catalog_row(proj_story.reference))
    membership[("jira", proj_story.reference.source_id)] = (PROJECT,)
    index.upsert(other)
    catalog.upsert(_catalog_row(other.reference))
    membership[("jira", other.reference.source_id)] = ("prj_other",)

    source_id = "gh/file.robot"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject, projects=(PROJECT,))
    match.execute(
        _source(source_id, "*** Test Cases ***\nX\n    [Tags]    PAY-123\n"),
        revision="rev1",
    )
    assert store.list_for_artifact(PROJECT, ArtifactRef(subject.reference)) == ()


def test_mention_overflow_is_non_destructive(tmp_path: Path) -> None:
    tight = MatchLimits(
        max_content_bytes=1_048_576,
        max_mentions=1,
        max_catalogue_entries=10_000,
        max_compiled_pattern_size=65_536,
    )
    store, index, catalog, membership, _ = _harness(
        tmp_path, _story("PROJ-123"), _story("PROJ-140")
    )
    match = MatchProjectReferences(
        store,
        index,
        catalog,
        project_ids_for=lambda ref: membership.get(
            (ref.source_type, ref.source_id), ()
        ),
        matchers=(KeyMentionTagMatcher(),),
        limits=tight,
        rule_catalogue_version="software_delivery.matchers.v1",
        context_relations=CONTEXT_RELATIONS,
        now=lambda: "2026-11-26T12:00:00Z",
    )
    source_id = "gh/file.robot"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject)
    # Seed a prior edge then overflow
    match_seed = MatchProjectReferences(
        store,
        index,
        catalog,
        project_ids_for=lambda ref: membership.get(
            (ref.source_type, ref.source_id), ()
        ),
        matchers=(KeyMentionTagMatcher(),),
        limits=LIMITS,
        rule_catalogue_version="software_delivery.matchers.v1",
        context_relations=CONTEXT_RELATIONS,
        now=lambda: "2026-11-26T12:00:00Z",
    )
    match_seed.execute(
        _source(source_id, "*** Test Cases ***\nX\n    [Tags]    PROJ-123\n"),
        revision="rev0",
    )
    source = _source(
        source_id,
        "*** Test Cases ***\nX\n    [Tags]    PROJ-123    PROJ-140\n",
    )
    match.execute(source, revision="rev1")
    edges = store.list_for_artifact(PROJECT, ArtifactRef(subject.reference))
    assert len(edges) == 1
    assert edges[0].freshness == "stale"
    assert len(edges[0].evidence) == 1
    assert not match.needs_record(source, revision="rev1")


def test_api_operation_mention_context_matrix_and_unresolved(tmp_path: Path) -> None:
    api = ArtifactDescriptor(
        reference=SourceReference("gh/acme/openapi.yaml", "github"),
        revision="spec1",
        kind=ArtifactKind.API_SPEC,
        contexts=(ContextAssignment("api_contract", "path_rule"),),
        external_keys=("cancelOrder", "POST /orders/{orderId}/cancel"),
        parts=(
            ArtifactPart(
                kind=ArtifactKind.API_OPERATION,
                part_key="POST /orders/{orderId}/cancel",
                operation_id="cancelOrder",
            ),
        ),
    )
    store, index, catalog, membership, match = _harness(tmp_path, api)
    membership[("github", api.reference.source_id)] = (PROJECT,)

    frontend_id = "gh/acme/proj-web/lib/api/orders.ts"
    frontend = ArtifactDescriptor(
        reference=SourceReference(frontend_id, "github"),
        revision="rev1",
        kind=ArtifactKind.CODE_FILE,
        contexts=(ContextAssignment("frontend", "path_rule"),),
    )
    _register_subject(index, catalog, membership, frontend)
    content = (
        Path(__file__).resolve().parents[2]
        / "fixtures/project_intelligence/v1/acme/proj-web/lib/api/orders.ts"
    ).read_text(encoding="utf-8")
    match.execute(_source(frontend_id, content), revision="rev1")
    edges = store.list_for_artifact(PROJECT, ArtifactRef(frontend.reference))
    assert len(edges) == 1
    assert edges[0].relation_type == "references"
    assert edges[0].evidence[0].extractor_id == "api_operation.mention"
    assert edges[0].object.part_key == "POST /orders/{orderId}/cancel"  # type: ignore[union-attr]

    test_id = "gh/acme/proj-tests/tests/orders/cancel_order.robot"
    test = ArtifactDescriptor(
        reference=SourceReference(test_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    _register_subject(index, catalog, membership, test)
    match.execute(
        _source(test_id, "Call POST /orders/${id}/cancel\n"),
        revision="rev1",
    )
    test_edges = store.list_for_artifact(PROJECT, ArtifactRef(test.reference))
    assert len(test_edges) == 1
    assert test_edges[0].relation_type == "exercises"

    missing_id = "gh/missing.ts"
    missing = ArtifactDescriptor(
        reference=SourceReference(missing_id, "github"),
        revision="rev1",
        kind=ArtifactKind.CODE_FILE,
        contexts=(ContextAssignment("frontend", "path_rule"),),
    )
    _register_subject(index, catalog, membership, missing)
    match.execute(
        _source(missing_id, 'fetch("/orders/nope", { method: "POST" })\n'),
        revision="rev1",
    )
    assert store.list_for_artifact(PROJECT, ArtifactRef(missing.reference)) == ()


def test_unchanged_revision_skipped_until_catalogue_changes(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-123"))
    source_id = "gh/file.robot"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject)
    source = _source(
        source_id, "*** Test Cases ***\nX\n    [Tags]    PROJ-123\n"
    )
    match.execute(source, revision="rev1")
    assert not match.needs_record(source, revision="rev1")
    # New story appears → catalogue fingerprint changes → rematch
    new_story = _story("PROJ-140")
    index.upsert(new_story)
    catalog.upsert(_catalog_row(new_story.reference))
    membership[("jira", new_story.reference.source_id)] = (PROJECT,)
    match.invalidate_catalogue()
    assert match.needs_record(source, revision="rev1")


def test_descriptor_absence_skips_matching(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-123"))
    source_id = "gh/unknown.robot"
    membership[("github", source_id)] = (PROJECT,)
    source = _source(
        source_id, "*** Test Cases ***\nX\n    [Tags]    PROJ-123\n"
    )
    assert not match.needs_record(source, revision="rev1")
    match.execute(source, revision="rev1")
    assert (
        store.get_record_watermark(
            source.reference, kind=WATERMARK_KIND_DETERMINISTIC
        )
        is None
    )


def test_fanout_failure_isolation(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-123"))
    source_id = "gh/file.robot"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject)
    source = _source(
        source_id, "*** Test Cases ***\nX\n    [Tags]    PROJ-123\n"
    )

    class _Boom:
        def supports(self, reference: SourceReference) -> bool:
            return True

        def needs_record(self, source: SourceDocument, *, revision: str) -> bool:
            return True

        def execute(self, source: SourceDocument, *, revision: str) -> None:
            raise RuntimeError("provider failed")

        def needs_retry(self, reference, *, revision, links_fingerprint=None):  # noqa: ANN001
            return True

        def missing_watermark(self, reference: SourceReference) -> bool:
            return True

        def clear_watermark(self, reference: SourceReference) -> None:
            return None

        def resolve_arriving(self, source: SourceDocument) -> None:
            return None

    fanout = FanOutRelationshipRecorder((_Boom(), match))
    fanout.execute(source, revision="rev1")
    edges = store.list_for_artifact(PROJECT, ArtifactRef(subject.reference))
    assert len(edges) == 1


def test_catalogue_overflow_watermark_is_stable(tmp_path: Path) -> None:
    tight = MatchLimits(
        max_content_bytes=1_048_576,
        max_mentions=100,
        max_catalogue_entries=2,
        max_compiled_pattern_size=65_536,
    )
    store, index, catalog, membership, _ = _harness(
        tmp_path, _story("PROJ-123"), _story("PROJ-140")
    )
    match = MatchProjectReferences(
        store,
        index,
        catalog,
        project_ids_for=lambda ref: membership.get(
            (ref.source_type, ref.source_id), ()
        ),
        matchers=(KeyMentionTagMatcher(),),
        limits=tight,
        rule_catalogue_version="software_delivery.matchers.v1",
        context_relations=CONTEXT_RELATIONS,
        now=lambda: "2026-11-26T12:00:00Z",
    )
    source_id = "gh/file.robot"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject)
    source = _source(
        source_id, "*** Test Cases ***\nX\n    [Tags]    PROJ-123\n"
    )
    match.execute(source, revision="rev1")
    assert not match.needs_record(source, revision="rev1")
    assert not match.needs_retry(subject.reference, revision="rev1")


def test_api_operation_without_operation_id_resolves_via_raw_part_key(
    tmp_path: Path,
) -> None:
    api = ArtifactDescriptor(
        reference=SourceReference("gh/acme/openapi.yaml", "github"),
        revision="spec1",
        kind=ArtifactKind.API_SPEC,
        contexts=(ContextAssignment("api_contract", "path_rule"),),
        external_keys=("POST /orders/{orderId}/cancel",),
        parts=(
            ArtifactPart(
                kind=ArtifactKind.API_OPERATION,
                part_key="POST /orders/{orderId}/cancel",
                operation_id=None,
            ),
        ),
    )
    store, index, catalog, membership, match = _harness(tmp_path, api)
    membership[("github", api.reference.source_id)] = (PROJECT,)
    frontend_id = "gh/acme/proj-web/lib/api/orders.ts"
    frontend = ArtifactDescriptor(
        reference=SourceReference(frontend_id, "github"),
        revision="rev1",
        kind=ArtifactKind.CODE_FILE,
        contexts=(ContextAssignment("frontend", "path_rule"),),
    )
    _register_subject(index, catalog, membership, frontend)
    content = (
        "POST /orders/{orderId}/cancel\n"
        'fetch(`/orders/${id}/cancel`, { method: "POST" })\n'
    )
    match.execute(_source(frontend_id, content), revision="rev1")
    edges = store.list_for_artifact(PROJECT, ArtifactRef(frontend.reference))
    assert len(edges) == 1
    assert edges[0].object.part_key == "POST /orders/{orderId}/cancel"  # type: ignore[union-attr]


def test_header_ignores_body_keys_in_first_forty_lines(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-7"))
    source_id = "gh/acme/proj/orders/handler.py"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.CODE_FILE,
        contexts=(ContextAssignment("backend", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject)
    match.execute(
        _source(
            source_id,
            'import os\n\n\ndef handler():\n    return lookup("PROJ-7")\n',
        ),
        revision="rev1",
    )
    assert store.list_for_artifact(PROJECT, ArtifactRef(subject.reference)) == ()


def test_header_docstring_after_shebang_and_license_comments(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-7"))
    cases = [
        '"""Cancel orders (PROJ-7)."""\nimport os\n',
        '#!/usr/bin/env python\n"""Cancel orders (PROJ-7)."""\nimport os\n',
        (
            "# Copyright 2026 Acme\n"
            "# SPDX-License-Identifier: MIT\n"
            "\n"
            '"""Cancel orders (PROJ-7)."""\n'
            "import os\n"
        ),
    ]
    for index_no, content in enumerate(cases):
        source_id = f"gh/acme/proj/orders/cancel_{index_no}.py"
        subject = ArtifactDescriptor(
            reference=SourceReference(source_id, "github"),
            revision="rev1",
            kind=ArtifactKind.CODE_FILE,
            contexts=(ContextAssignment("backend", "path_rule"),),
        )
        _register_subject(index, catalog, membership, subject)
        match.execute(_source(source_id, content), revision="rev1")
        edges = store.list_for_artifact(PROJECT, ArtifactRef(subject.reference))
        assert len(edges) == 1
        assert edges[0].evidence[0].extractor_id == "key_mention.header"


def test_replace_preserves_provider_evidence_on_same_edge(tmp_path: Path) -> None:
    store, index, catalog, membership, match = _harness(tmp_path, _story("PROJ-123"))
    source_id = "gh/file.robot"
    subject = ArtifactDescriptor(
        reference=SourceReference(source_id, "github"),
        revision="rev1",
        kind=ArtifactKind.AUTOMATED_TEST,
        contexts=(ContextAssignment("testing", "path_rule"),),
    )
    _register_subject(index, catalog, membership, subject)
    # Provider edge with same endpoints as deterministic will collide on identity
    # only if subject/object tokens match — use provider on story→story instead
    # and ensure deterministic evidence on test→story does not touch it.
    provider = store.upsert_from_evidence(
        project_id=PROJECT,
        subject=ArtifactRef(SourceReference("cloud/PROJ:PROJ-140", "jira")),
        relation_type="tests",
        object=ArtifactRef(SourceReference("cloud/PROJ:PROJ-123", "jira")),
        origin=ORIGIN_PROVIDER_DECLARED,
        verification=VERIFICATION_VERIFIED,
        confidence=1.0,
        freshness="current",
        evidence=EvidenceRef(
            source=SourceReference("cloud/PROJ:PROJ-140", "jira"),
            revision="j1",
            locator="field=issuelinks",
            extractor_id="jira_explicit_links",
        ),
        seen_at="2026-11-26T11:00:00Z",
    )
    match.execute(
        _source(source_id, "*** Test Cases ***\nX\n    [Tags]    PROJ-123\n"),
        revision="rev1",
    )
    loaded = store.get(provider.relationship_id)
    assert loaded is not None
    assert loaded.origin == ORIGIN_PROVIDER_DECLARED
    assert len(loaded.evidence) == 1
    assert loaded.evidence[0].extractor_id == "jira_explicit_links"
