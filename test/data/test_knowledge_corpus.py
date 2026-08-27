"""Validate the generic knowledge seed corpus against its JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "data" / "knowledge"
SCHEMA_PATH = KNOWLEDGE_DIR / "schema.json"
DOCUMENTS_PATH = KNOWLEDGE_DIR / "documents.json"

_REQUIRED_FIELDS = (
    "source_id",
    "title",
    "doc_type",
    "content",
    "status",
    "version",
)

# Representative categories for the committed heterogeneous fixture — examples,
# not an allow-list the adapter or schema should enforce.
_EXPECTED_DOC_TYPES = frozenset(
    {"openapi", "user_story", "bug", "source_code", "srs", "qa_guidance"}
)


@pytest.fixture(scope="module")
def schema() -> dict:
    """Load the corpus document schema."""
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def documents() -> list[dict]:
    """Load the seed corpus documents."""
    payload = json.loads(DOCUMENTS_PATH.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return payload


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    """Build a Draft 2020-12 validator for one document object."""
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_seed_corpus_is_non_empty(documents: list[dict]) -> None:
    assert documents


def test_every_document_matches_schema(
    documents: list[dict], validator: Draft202012Validator
) -> None:
    for document in documents:
        errors = sorted(validator.iter_errors(document), key=lambda e: e.path)
        assert not errors, (
            f"schema errors for {document.get('source_id')!r}: "
            + "; ".join(error.message for error in errors)
        )


def test_required_fields_are_non_blank_strings(documents: list[dict]) -> None:
    for document in documents:
        for field_name in _REQUIRED_FIELDS:
            value = document[field_name]
            assert isinstance(value, str) and value.strip(), (
                f"{document.get('source_id')!r} field {field_name!r} "
                f"must be a non-blank string, got {value!r}"
            )


def test_doc_type_is_any_non_blank_string(
    documents: list[dict], schema: dict
) -> None:
    doc_type_schema = schema["properties"]["doc_type"]
    assert "enum" not in doc_type_schema
    assert doc_type_schema.get("minLength", 0) >= 1
    for document in documents:
        assert isinstance(document["doc_type"], str)
        assert document["doc_type"].strip()


def test_source_ids_are_unique(documents: list[dict]) -> None:
    source_ids = [document["source_id"] for document in documents]
    assert len(source_ids) == len(set(source_ids))


def test_all_seed_documents_are_approved(documents: list[dict]) -> None:
    assert all(document["status"] == "approved" for document in documents)


def test_optional_tags_are_arrays_of_non_blank_strings(
    documents: list[dict],
) -> None:
    for document in documents:
        tags = document.get("tags")
        if tags is None:
            continue
        assert isinstance(tags, list), (
            f"tags for {document['source_id']!r} must be an array, got {tags!r}"
        )
        for tag in tags:
            assert isinstance(tag, str) and tag.strip(), (
                f"tag for {document['source_id']!r} must be non-blank, got {tag!r}"
            )


def test_seed_corpus_includes_heterogeneous_categories(
    documents: list[dict],
) -> None:
    present = {document["doc_type"] for document in documents}
    missing = _EXPECTED_DOC_TYPES - present
    assert not missing, f"seed corpus missing representative doc_types: {missing}"


def test_source_urls_are_well_formed_when_present(documents: list[dict]) -> None:
    for document in documents:
        source_url = document.get("source_url")
        if source_url is None:
            continue
        parsed = urlparse(source_url)
        assert parsed.scheme in {"http", "https", "file"}, (
            f"unsupported source_url scheme for {document['source_id']!r}: "
            f"{source_url!r}"
        )
        assert parsed.netloc or parsed.path, (
            f"incomplete source_url for {document['source_id']!r}: {source_url!r}"
        )
