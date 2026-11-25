"""Jira ExplicitLinkExtractor: canonical links and stable locators (#374)."""

from __future__ import annotations

import json

import pytest

from domain.knowledge import SourceDocument, SourceMetadata, SourceReference, SourceType
from infrastructure.connectors.jira.link_extractor import (
    PROVIDER_LINKS_EXTRA_KEY,
    JiraExplicitLinkExtractor,
    decode_provider_links_raw,
    encode_provider_links,
)


def _document(
    key: str = "PROJ-140",
    *,
    links_payload: dict[str, object] | None = None,
) -> SourceDocument:
    extra = {
        "jira_issue_key": key,
        "jira_issue_type": "Test",
        "jira_updated_at": "2026-10-01T12:00:00.000+0000",
        "jira_instance_id": "inst",
        "jira_project_key": "PROJ",
    }
    if links_payload is not None:
        extra[PROVIDER_LINKS_EXTRA_KEY] = encode_provider_links(links_payload)
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(f"inst/PROJ:{key}", SourceType.JIRA),
            title=f"{key}: title",
            provider="jira",
            content_format="markdown",
            extra=extra,
        ),
        f"# {key}",
    )


def test_extract_tests_link_canonicalizes_outward_and_inward() -> None:
    extractor = JiraExplicitLinkExtractor()
    outward_doc = _document(
        "PROJ-140",
        links_payload={
            "v": 1,
            "issue_key": "PROJ-140",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "Tests",
                    "direction": "outward",
                    "other_key": "PROJ-123",
                }
            ],
        },
    )
    inward_doc = _document(
        "PROJ-123",
        links_payload={
            "v": 1,
            "issue_key": "PROJ-123",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "Tests",
                    "direction": "inward",
                    "other_key": "PROJ-140",
                }
            ],
        },
    )

    outward = extractor.extract(
        outward_doc, decode_provider_links_raw(outward_doc.metadata.extra)
    )
    inward = extractor.extract(
        inward_doc, decode_provider_links_raw(inward_doc.metadata.extra)
    )

    assert len(outward) == 1
    assert outward[0].relation_type == "tests"
    assert outward[0].subject_key == "PROJ-140"
    assert outward[0].object_key == "PROJ-123"
    assert outward[0].locator == (
        "field=issuelinks;type=Tests;dir=out;key=PROJ-123"
    )
    assert len(inward) == 1
    assert inward[0].relation_type == "tests"
    assert inward[0].subject_key == "PROJ-140"
    assert inward[0].object_key == "PROJ-123"
    assert inward[0].locator == (
        "field=issuelinks;type=Tests;dir=in;key=PROJ-140"
    )


def test_extract_parent_and_subtask_become_child_of() -> None:
    extractor = JiraExplicitLinkExtractor()
    child = _document(
        "PROJ-2",
        links_payload={
            "v": 1,
            "issue_key": "PROJ-2",
            "links": [
                {
                    "field": "parent",
                    "type_name": "parent",
                    "direction": "outward",
                    "other_key": "PROJ-1",
                }
            ],
        },
    )
    parent = _document(
        "PROJ-1",
        links_payload={
            "v": 1,
            "issue_key": "PROJ-1",
            "links": [
                {
                    "field": "subtasks",
                    "type_name": "subtask",
                    "direction": "outward",
                    "other_key": "PROJ-2",
                }
            ],
        },
    )

    from_child = extractor.extract(
        child, decode_provider_links_raw(child.metadata.extra)
    )
    from_parent = extractor.extract(
        parent, decode_provider_links_raw(parent.metadata.extra)
    )

    assert from_child[0].relation_type == "child_of"
    assert from_child[0].subject_key == "PROJ-2"
    assert from_child[0].object_key == "PROJ-1"
    assert from_child[0].locator == "field=parent;key=PROJ-1"
    assert from_parent[0].relation_type == "child_of"
    assert from_parent[0].subject_key == "PROJ-2"
    assert from_parent[0].object_key == "PROJ-1"
    assert from_parent[0].locator == "field=subtasks;key=PROJ-2"


def test_unknown_link_type_kept_as_jira_prefixed_token() -> None:
    extractor = JiraExplicitLinkExtractor()
    doc = _document(
        links_payload={
            "v": 1,
            "issue_key": "PROJ-140",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "Weird Custom",
                    "direction": "outward",
                    "other_key": "PROJ-50",
                }
            ],
        },
    )

    links = extractor.extract(doc, decode_provider_links_raw(doc.metadata.extra))

    assert links[0].relation_type == "jira:Weird_Custom"
    assert links[0].subject_key == "PROJ-140"
    assert links[0].object_key == "PROJ-50"


def test_locator_stable_across_identical_reextracts() -> None:
    extractor = JiraExplicitLinkExtractor()
    payload = {
        "v": 1,
        "issue_key": "PROJ-130",
        "links": [
            {
                "field": "issuelinks",
                "type_name": "Relates",
                "direction": "outward",
                "other_key": "PROJ-123",
            }
        ],
    }
    doc = _document("PROJ-130", links_payload=payload)
    raw = decode_provider_links_raw(doc.metadata.extra)

    first = extractor.extract(doc, raw)
    second = extractor.extract(doc, raw)

    assert first == second
    assert first[0].locator == (
        "field=issuelinks;type=Relates;dir=out;key=PROJ-123"
    )
    assert first[0].relation_type == "relates_to"


def test_passive_outward_phrase_keeps_canonical_direction() -> None:
    extractor = JiraExplicitLinkExtractor()
    caused_by = _document(
        "BUG-2",
        links_payload={
            "v": 1,
            "issue_key": "BUG-2",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "Problem/Incident",
                    "direction": "outward",
                    "other_key": "STORY-1",
                    "type_outward": "is caused by",
                }
            ],
        },
    )
    tested_by = _document(
        "STORY-1",
        links_payload={
            "v": 1,
            "issue_key": "STORY-1",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "Tests",
                    "direction": "outward",
                    "other_key": "TEST-9",
                    "type_outward": "is tested by",
                }
            ],
        },
    )

    caused = extractor.extract(
        caused_by, decode_provider_links_raw(caused_by.metadata.extra)
    )
    tested = extractor.extract(
        tested_by, decode_provider_links_raw(tested_by.metadata.extra)
    )

    assert caused[0].relation_type == "affects"
    assert caused[0].subject_key == "STORY-1"
    assert caused[0].object_key == "BUG-2"
    assert tested[0].relation_type == "tests"
    assert tested[0].subject_key == "TEST-9"
    assert tested[0].object_key == "STORY-1"


def test_xray_test_type_maps_via_name_and_phrases() -> None:
    extractor = JiraExplicitLinkExtractor()
    by_name = _document(
        "PROJ-140",
        links_payload={
            "v": 1,
            "issue_key": "PROJ-140",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "Test",
                    "direction": "outward",
                    "other_key": "PROJ-123",
                    "type_inward": "is tested by",
                    "type_outward": "tests",
                }
            ],
        },
    )
    by_phrase = _document(
        "PROJ-140",
        links_payload={
            "v": 1,
            "issue_key": "PROJ-140",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "Problem/Incident",
                    "direction": "outward",
                    "other_key": "PROJ-123",
                    "type_outward": "causes",
                }
            ],
        },
    )

    named = extractor.extract(
        by_name, decode_provider_links_raw(by_name.metadata.extra)
    )
    phrased = extractor.extract(
        by_phrase, decode_provider_links_raw(by_phrase.metadata.extra)
    )

    assert named[0].relation_type == "tests"
    assert named[0].subject_key == "PROJ-140"
    assert named[0].object_key == "PROJ-123"
    assert phrased[0].relation_type == "affects"


def test_non_ascii_link_types_stay_distinct() -> None:
    extractor = JiraExplicitLinkExtractor()
    first = _document(
        links_payload={
            "v": 1,
            "issue_key": "PROJ-140",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "関連",
                    "direction": "outward",
                    "other_key": "PROJ-50",
                }
            ],
        },
    )
    second = _document(
        links_payload={
            "v": 1,
            "issue_key": "PROJ-140",
            "links": [
                {
                    "field": "issuelinks",
                    "type_name": "依存",
                    "direction": "outward",
                    "other_key": "PROJ-50",
                }
            ],
        },
    )

    a = extractor.extract(first, decode_provider_links_raw(first.metadata.extra))
    b = extractor.extract(second, decode_provider_links_raw(second.metadata.extra))

    assert a[0].relation_type == "jira:関連"
    assert b[0].relation_type == "jira:依存"
    assert a[0].relation_type != b[0].relation_type


def test_build_payload_keeps_inward_outward_phrases() -> None:
    from infrastructure.connectors.jira.link_extractor import (
        build_provider_links_payload,
    )

    payload = build_provider_links_payload(
        issue_key="PROJ-140",
        fields={
            "issuelinks": [
                {
                    "type": {
                        "name": "Test",
                        "inward": "is tested by",
                        "outward": "tests",
                    },
                    "outwardIssue": {"key": "PROJ-123"},
                }
            ]
        },
    )

    assert payload["links"][0]["type_name"] == "Test"
    assert payload["links"][0]["type_inward"] == "is tested by"
    assert payload["links"][0]["type_outward"] == "tests"


def test_encode_round_trip_versioned_payload() -> None:
    payload = {"v": 1, "issue_key": "PROJ-1", "links": []}
    encoded = encode_provider_links(payload)
    assert json.loads(encoded)["v"] == 1
    assert decode_provider_links_raw({PROVIDER_LINKS_EXTRA_KEY: encoded}) == payload


def test_decode_rejects_missing_or_wrong_version() -> None:
    with pytest.raises(ValueError):
        decode_provider_links_raw({})
    with pytest.raises(ValueError):
        decode_provider_links_raw(
            {PROVIDER_LINKS_EXTRA_KEY: json.dumps({"v": 2, "links": []})}
        )
