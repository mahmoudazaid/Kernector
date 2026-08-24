"""Validate the Story Intelligence seed corpus against its JSON Schema."""

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


def test_source_ids_are_unique(documents: list[dict]) -> None:
    source_ids = [document["source_id"] for document in documents]
    assert len(source_ids) == len(set(source_ids))


def test_all_seed_documents_are_approved(documents: list[dict]) -> None:
    assert all(document["status"] == "approved" for document in documents)


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
