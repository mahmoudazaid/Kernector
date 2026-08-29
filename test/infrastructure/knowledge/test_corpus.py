"""Behavior tests for the JSON knowledge-corpus adapter.

Every assertion goes through `load_knowledge_corpus` and the public adapter
errors. Temporary corpus files under `tmp_path` and committed corpora under
`data/knowledge/` are the behavior under test — nothing mocks `Path` or `json`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.knowledge import SourceType
from infrastructure.knowledge.corpus import (
    CorpusLoadError,
    CorpusNotFoundError,
    CorpusParseError,
    CorpusValidationError,
    load_knowledge_corpus,
)


def _write_corpus(path: Path, records: list[object]) -> Path:
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def test_generic_record_becomes_source_document(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [
            {
                "source_id": "architecture-001",
                "title": "Service boundaries",
                "doc_type": "architecture_decision",
                "content": "The application layer depends only on domain ports.",
                "status": "approved",
                "version": "1.0",
            }
        ],
    )

    documents = load_knowledge_corpus(corpus)

    assert isinstance(documents, tuple)
    assert len(documents) == 1
    document = documents[0]
    assert document.source_id == "architecture-001"
    assert document.metadata.title == "Service boundaries"
    assert document.content == (
        "The application layer depends only on domain ports."
    )
    assert document.reference.source_type is SourceType.KNOWLEDGE_DOCUMENT
    assert document.metadata.extra["doc_type"] == "architecture_decision"


def test_missing_file_raises_typed_error_naming_path(tmp_path: Path) -> None:
    missing = tmp_path / "absent" / "corpus.json"

    with pytest.raises(CorpusNotFoundError, match=str(missing)) as exc_info:
        load_knowledge_corpus(missing)

    assert isinstance(exc_info.value, CorpusLoadError)


def test_unreadable_file_raises_load_error_naming_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus = _write_corpus(tmp_path / "corpus.json", [])

    def _boom(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("simulated read failure")

    monkeypatch.setattr(Path, "read_text", _boom)

    with pytest.raises(CorpusLoadError, match=str(corpus)) as exc_info:
        load_knowledge_corpus(corpus)

    assert not isinstance(exc_info.value, CorpusNotFoundError)
    assert isinstance(exc_info.value.__cause__, OSError)


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        b"\xff\xfe not utf-8",
    ],
    ids=["truncated_json", "invalid_utf8"],
)
def test_malformed_payload_raises_parse_error(
    tmp_path: Path, raw: str | bytes
) -> None:
    path = tmp_path / "corpus.json"
    if isinstance(raw, bytes):
        path.write_bytes(raw)
    else:
        path.write_text(raw, encoding="utf-8")

    with pytest.raises(CorpusParseError):
        load_knowledge_corpus(path)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        "not-an-array",
        42,
        True,
        None,
    ],
    ids=["object", "string", "number", "boolean", "null"],
)
def test_non_array_root_raises_validation_error(
    tmp_path: Path, payload: object
) -> None:
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorpusValidationError):
        load_knowledge_corpus(path)


def test_empty_array_is_valid(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path / "corpus.json", [])
    assert load_knowledge_corpus(corpus) == ()


_REQUIRED_FIELDS = (
    "source_id",
    "title",
    "doc_type",
    "content",
    "status",
    "version",
)


def _valid_record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "source_id": "doc-001",
        "title": "Title",
        "doc_type": "note",
        "content": "Body",
        "status": "approved",
        "version": "1.0",
    }
    record.update(overrides)
    return record


@pytest.mark.parametrize(
    "entry",
    ["text", 1, True, [], None],
    ids=["string", "number", "boolean", "array", "null"],
)
def test_non_object_record_raises_validation_error_with_index(
    tmp_path: Path, entry: object
) -> None:
    corpus = _write_corpus(tmp_path / "corpus.json", [entry])

    with pytest.raises(CorpusValidationError, match=r"record 0") as exc_info:
        load_knowledge_corpus(corpus)

    assert "must be an object" in str(exc_info.value)


@pytest.mark.parametrize("field_name", _REQUIRED_FIELDS)
@pytest.mark.parametrize(
    "bad_value",
    [pytest.param(None, id="null"), pytest.param(1, id="non_string")],
)
def test_required_field_wrong_type_raises_with_index_and_name(
    tmp_path: Path, field_name: str, bad_value: object
) -> None:
    invalid = _valid_record(**{field_name: bad_value})
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [_valid_record(source_id="ok-001"), invalid],
    )

    with pytest.raises(CorpusValidationError) as exc_info:
        load_knowledge_corpus(corpus)

    message = str(exc_info.value)
    assert "record 1" in message
    assert field_name in message


@pytest.mark.parametrize("field_name", _REQUIRED_FIELDS)
@pytest.mark.parametrize(
    "bad_value",
    [pytest.param("", id="empty"), pytest.param("   ", id="whitespace")],
)
def test_required_field_blank_raises_with_index_and_name(
    tmp_path: Path, field_name: str, bad_value: str
) -> None:
    invalid = _valid_record(**{field_name: bad_value})
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [_valid_record(source_id="ok-001"), invalid],
    )

    with pytest.raises(CorpusValidationError) as exc_info:
        load_knowledge_corpus(corpus)

    message = str(exc_info.value)
    assert "record 1" in message
    assert field_name in message


@pytest.mark.parametrize("field_name", _REQUIRED_FIELDS)
def test_missing_required_field_raises_with_index_and_name(
    tmp_path: Path, field_name: str
) -> None:
    invalid = _valid_record()
    del invalid[field_name]
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [_valid_record(source_id="ok-001"), invalid],
    )

    with pytest.raises(CorpusValidationError) as exc_info:
        load_knowledge_corpus(corpus)

    message = str(exc_info.value)
    assert "record 1" in message
    assert field_name in message


def test_duplicate_source_id_is_rejected(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [
            _valid_record(source_id="dup-001", doc_type="openapi"),
            _valid_record(
                source_id="dup-001",
                title="Second",
                doc_type="bug",
                content="Other body",
            ),
        ],
    )

    with pytest.raises(CorpusValidationError) as exc_info:
        load_knowledge_corpus(corpus)

    message = str(exc_info.value)
    assert "dup-001" in message
    assert "record 1" in message


def test_optional_metadata_is_normalized_into_extra(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [
            _valid_record(
                source_id="payments-api-v1",
                title="Create payment endpoint",
                doc_type="openapi",
                content="POST /payments creates a payment.",
                tags=["api", "payments"],
                severity=None,
                component="payment-service",
                api_version="v1",
            )
        ],
    )

    document = load_knowledge_corpus(corpus)[0]
    extra = document.metadata.extra

    assert extra["tags_json"] == '["api","payments"]'
    assert "severity" not in extra
    assert extra["component"] == "payment-service"
    assert extra["api_version"] == "v1"
    assert extra["doc_type"] == "openapi"
    assert extra["status"] == "approved"
    assert extra["version"] == "1.0"


def test_unicode_metadata_is_preserved(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [
            _valid_record(
                source_id="ar-001",
                title="حدود الخدمة",
                content="تعتمد طبقة التطبيق على منافذ المجال فقط.",
                component="تحليل-القصة",
                tags=["جودة", "اختبار"],
            )
        ],
    )

    document = load_knowledge_corpus(corpus)[0]

    assert document.metadata.title == "حدود الخدمة"
    assert document.content == "تعتمد طبقة التطبيق على منافذ المجال فقط."
    assert document.metadata.extra["component"] == "تحليل-القصة"
    assert document.metadata.extra["tags_json"] == '["جودة","اختبار"]'


def test_nested_metadata_object_is_rejected(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [_valid_record(owner={"team": "payments"})],
    )

    with pytest.raises(CorpusValidationError, match=r"record 0"):
        load_knowledge_corpus(corpus)


REPO_ROOT = Path(__file__).resolve().parents[3]
NEUTRAL_DEFAULT_CORPUS = REPO_ROOT / "data" / "knowledge" / "documents.json"
STORY_INTELLIGENCE_PACK = (
    REPO_ROOT / "data" / "knowledge" / "packs" / "story-intelligence" / "documents.json"
)


def test_arbitrary_non_sdlc_extras_are_preserved_in_extra(tmp_path: Path) -> None:
    corpus = _write_corpus(
        tmp_path / "corpus.json",
        [
            _valid_record(
                source_id="policy-leave-001",
                title="Leave request window",
                doc_type="policy",
                content="Request leave ten business days in advance.",
                audience="all-staff",
                region="global",
            )
        ],
    )

    document = load_knowledge_corpus(corpus)[0]
    extra = document.metadata.extra

    assert extra["doc_type"] == "policy"
    assert extra["audience"] == "all-staff"
    assert extra["region"] == "global"
    assert "severity" not in extra
    assert "component" not in extra


def test_committed_neutral_default_corpus_loads() -> None:
    raw = json.loads(NEUTRAL_DEFAULT_CORPUS.read_text(encoding="utf-8"))
    assert isinstance(raw, list)

    documents = load_knowledge_corpus(NEUTRAL_DEFAULT_CORPUS)

    assert len(documents) == len(raw)
    assert {document.reference.source_type for document in documents} == {
        SourceType.KNOWLEDGE_DOCUMENT
    }
    assert "openapi-payments-001" not in {
        document.source_id for document in documents
    }


def test_committed_story_intelligence_pack_loads() -> None:
    raw = json.loads(STORY_INTELLIGENCE_PACK.read_text(encoding="utf-8"))
    assert isinstance(raw, list)

    documents = load_knowledge_corpus(STORY_INTELLIGENCE_PACK)

    assert len(documents) == len(raw)
    by_id = {document.source_id: document for document in documents}

    openapi = by_id["openapi-payments-001"]
    assert openapi.metadata.extra["doc_type"] == "openapi"
    assert openapi.reference.source_type is SourceType.KNOWLEDGE_DOCUMENT
    assert openapi.metadata.extra["tags_json"] == '["payments","api"]'
    assert "severity" not in openapi.metadata.extra

    bug = by_id["bug-auth-001"]
    assert bug.metadata.extra["doc_type"] == "bug"
    assert bug.reference.source_type is SourceType.KNOWLEDGE_DOCUMENT

    srs = by_id["srs-auth-001"]
    assert srs.metadata.extra["doc_type"] == "srs"
    assert srs.reference.source_type is SourceType.KNOWLEDGE_DOCUMENT

    source_code = by_id["code-ingest-001"]
    assert source_code.metadata.extra["doc_type"] == "source_code"
    assert source_code.reference.source_type is SourceType.KNOWLEDGE_DOCUMENT

    assert {document.reference.source_type for document in documents} == {
        SourceType.KNOWLEDGE_DOCUMENT
    }
