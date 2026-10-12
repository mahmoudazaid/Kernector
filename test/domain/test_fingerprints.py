"""Unit tests for content, metadata, and processing fingerprints."""

from datetime import UTC, datetime

import pytest

from domain.errors import DomainValidationError
from domain.knowledge import (
    ProcessingProfile,
    SourceMetadata,
    SourceReference,
    SourceType,
    fingerprint_metadata,
    fingerprint_text,
)

TEXT_DIGEST = "880553fca8fcea94e325ee2cfb48e5a985cc797f39a14cc6d3cedecfeb2ae4d2"
METADATA_DIGEST = "515a86f526977c30998135bd5e94764d7607694e6948b154f606e9f99af0a646"
EMPTY_METADATA_DIGEST = (
    "a6222c0e3a4480af68ad6d87ab2e1ab9db5a113fb57431dcf7609e6f6b52f7d5"
)
PROFILE_DIGEST = "45e15a4c30dd84b762d4485c06d87bf903c6463022fd97df32867148ede0c8c9"


def _metadata(**overrides: object) -> SourceMetadata:
    values: dict[str, object] = {
        "reference": SourceReference("1AbC", SourceType.GOOGLE_DRIVE),
        "title": "Spec",
        "provider": "google_drive",
        "content_format": "markdown",
        "extra": {"a": "1", "b": "2"},
    }
    values.update(overrides)
    return SourceMetadata(**values)  # type: ignore[arg-type]


def _profile(**overrides: object) -> ProcessingProfile:
    values: dict[str, object] = {
        "chunker_version": "1",
        "chunk_size": 500,
        "chunk_overlap": 50,
        "embedding_model": "qwen/qwen3-embedding-8b",
    }
    values.update(overrides)
    return ProcessingProfile(**values)  # type: ignore[arg-type]


def test_text_fingerprint_is_sha256_of_lf_text() -> None:
    assert fingerprint_text("a\nb\nc\n") == TEXT_DIGEST


@pytest.mark.parametrize("text", ["a\r\nb\r\nc\r\n", "a\rb\rc\r", "a\r\nb\rc\n"])
def test_text_fingerprint_normalizes_line_endings(text: str) -> None:
    assert fingerprint_text(text) == TEXT_DIGEST


def test_text_fingerprint_changes_with_content() -> None:
    assert fingerprint_text("a\nb\nc\nd\n") != TEXT_DIGEST


def test_text_fingerprint_keeps_other_whitespace() -> None:
    assert fingerprint_text("a\nb\nc\n ") != TEXT_DIGEST


def test_metadata_fingerprint_is_sha256_of_canonical_json() -> None:
    assert fingerprint_metadata(_metadata()) == METADATA_DIGEST


def test_metadata_fingerprint_of_empty_metadata() -> None:
    metadata = SourceMetadata(SourceReference("1AbC", SourceType.GOOGLE_DRIVE))
    assert fingerprint_metadata(metadata) == EMPTY_METADATA_DIGEST


def test_metadata_fingerprint_ignores_extra_key_order() -> None:
    assert fingerprint_metadata(_metadata(extra={"b": "2", "a": "1"})) == (
        METADATA_DIGEST
    )


def test_metadata_fingerprint_excludes_timestamps() -> None:
    stamped = _metadata(
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 2, 1, tzinfo=UTC),
    )
    assert fingerprint_metadata(stamped) == METADATA_DIGEST


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "Other"},
        {"provider": "github"},
        {"content_format": "text"},
        {"extra": {"a": "1", "b": "3"}},
        {"extra": {"a": "1"}},
    ],
)
def test_metadata_fingerprint_changes_with_described_fields(
    overrides: dict[str, object],
) -> None:
    assert fingerprint_metadata(_metadata(**overrides)) != METADATA_DIGEST


def test_processing_profile_fingerprint_is_sha256_of_canonical_json() -> None:
    assert _profile().fingerprint == PROFILE_DIGEST


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunker_version": "2"},
        {"chunk_size": 400},
        {"chunk_overlap": 0},
        {"embedding_model": "openai/text-embedding-3-small"},
    ],
)
def test_processing_profile_fingerprint_changes_with_each_field(
    overrides: dict[str, object],
) -> None:
    assert _profile(**overrides).fingerprint != PROFILE_DIGEST


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunker_version": " "},
        {"embedding_model": ""},
        {"chunk_size": 0},
        {"chunk_size": True},
        {"chunk_overlap": -1},
    ],
)
def test_processing_profile_rejects_invalid_fields(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(DomainValidationError):
        _profile(**overrides)
