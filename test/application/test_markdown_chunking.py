"""Structure-aware Markdown chunking: tables, retrieval context, plain-text parity."""

from __future__ import annotations

from application.chunking import chunk_document
from application.contracts import IngestRequest, RetrieveRequest
from application.ingest_knowledge import IngestKnowledge
from application.retrieve_knowledge import RetrieveKnowledge
from domain.knowledge import (
    SourceDocument,
    SourceMetadata,
    SourceReference,
    SourceType,
)
from infrastructure.config import ChromaSettings
from infrastructure.vectorstore.chroma import ChromaVectorStore
from test.doubles import StubEmbeddingModel

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
MFA_ROW = (
    "| 202 | MFA_REQUIRED | Password check succeeded, "
    "but a second factor is required. |"
)
TABLE_HEADER = "| Code | Name | Description |\n| --- | --- | --- |\n"


def _markdown_document(
    content: str,
    *,
    source_id: str = "api-doc",
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT),
            content_format="markdown",
        ),
        content,
    )


def _plain_document(content: str) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            SourceReference("plain", SourceType.KNOWLEDGE_DOCUMENT),
            content_format="txt",
        ),
        content,
    )


def _mfa_table_at_boundary(*, pad: int = 411) -> str:
    """Pad so naive 500-char windows split the MFA table row (regression fixture)."""
    return "x" * pad + "\n\n## API Responses\n\n" + TABLE_HEADER + MFA_ROW


def test_mfa_table_row_is_never_split_across_chunks() -> None:
    document = _markdown_document(_mfa_table_at_boundary())
    chunks = chunk_document(
        document, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )

    for chunk in chunks:
        has_code = "202" in chunk.content
        has_name = "MFA_REQUIRED" in chunk.content
        if has_code or has_name:
            assert has_code and has_name, chunk.content


def test_repeated_table_chunks_repeat_header_and_separator() -> None:
    rows = TABLE_HEADER + "\n".join(
        f"| {code} | STATUS_{code} | Description for status {code}. |"
        for code in range(300, 320)
    )
    document = _markdown_document(rows)
    chunks = chunk_document(
        document, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )

    assert len(chunks) >= 2
    for chunk in chunks:
        if "| 300 |" in chunk.content or "| 319 |" in chunk.content:
            assert "| Code | Name | Description |" in chunk.content
            assert "| --- | --- | --- |" in chunk.content


def test_markdown_ingest_retrieves_mfa_row_intact(tmp_path) -> None:
    store = ChromaVectorStore(
        ChromaSettings(persist_path=tmp_path / "chroma", collection="mfa-md")
    )
    embedding = StubEmbeddingModel()
    ingest = IngestKnowledge(
        embedding,
        store,
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    ingest.execute(
        IngestRequest(documents=[_markdown_document(_mfa_table_at_boundary())])
    )

    response = RetrieveKnowledge(
        embedding, store, max_input_length=10_000
    ).execute(
        RetrieveRequest(
            query="What API response represents MFA?", retrieval_limit=5
        )
    )

    assert response.hits
    assert any(
        "202" in hit.chunk.content and "MFA_REQUIRED" in hit.chunk.content
        for hit in response.hits
    )


def test_plain_text_chunking_unchanged_despite_markdown_like_content() -> None:
    text = "abcdefghij"
    document = _plain_document(text)
    chunks = chunk_document(document, chunk_size=5, chunk_overlap=2)

    assert [c.content for c in chunks] == ["abcde", "defgh", "ghij"]


def test_no_content_format_uses_character_windows() -> None:
    text = "abcdefghij"
    document = SourceDocument(
        SourceMetadata(SourceReference("doc", SourceType.KNOWLEDGE_DOCUMENT)),
        text,
    )
    chunks = chunk_document(document, chunk_size=5, chunk_overlap=2)

    assert [c.content for c in chunks] == ["abcde", "defgh", "ghij"]


def test_markdown_chunks_never_exceed_size_and_indices_are_contiguous() -> None:
    document = _markdown_document(_mfa_table_at_boundary())
    chunks = chunk_document(
        document, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP
    )

    assert [c.index for c in chunks] == list(range(len(chunks)))
    assert all(len(c.content) <= CHUNK_SIZE for c in chunks)
    assert all(c.content.strip() for c in chunks)
    assert all(c.metadata is document.metadata for c in chunks)
