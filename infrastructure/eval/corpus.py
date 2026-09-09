"""Load an eval corpus JSON array into SourceDocument values.

Unlike the knowledge seed loader, ``source_type`` is an open string and is not
forced to ``knowledge_document``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from domain.knowledge import SourceDocument, SourceMetadata, SourceReference

_REQUIRED_FIELDS = ("source_id", "source_type", "title", "content")


class EvalCorpusError(RuntimeError):
    """The eval corpus file could not be loaded or validated."""


def load_eval_corpus(path: Path) -> tuple[SourceDocument, ...]:
    """Load eval documents with open ``source_type`` values.

    Args:
        path (Path): JSON array of corpus records.

    Returns:
        tuple[SourceDocument, ...]: One document per record.

    Raises:
        EvalCorpusError: Missing file, invalid JSON, or invalid records.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise EvalCorpusError(f"eval corpus not found: {path}") from error
    except UnicodeDecodeError as error:
        raise EvalCorpusError(f"eval corpus is not valid UTF-8: {path}") from error
    except OSError as error:
        raise EvalCorpusError(f"eval corpus unreadable: {path}") from error
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise EvalCorpusError("eval corpus is not valid JSON") from error
    if not isinstance(payload, list):
        raise EvalCorpusError(
            f"eval corpus root must be a JSON array, got {type(payload).__name__}"
        )
    documents: list[SourceDocument] = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(payload):
        record = _require_record(entry, index)
        source_id = str(record["source_id"])
        if source_id in seen:
            raise EvalCorpusError(
                f"eval corpus record {index} duplicates source_id from record "
                f"{seen[source_id]}"
            )
        seen[source_id] = index
        documents.append(
            SourceDocument(
                metadata=SourceMetadata(
                    reference=SourceReference(
                        source_id, str(record["source_type"])
                    ),
                    title=str(record["title"]),
                ),
                content=str(record["content"]),
            )
        )
    return tuple(documents)


def _require_record(value: object, index: int) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise EvalCorpusError(
            f"eval corpus record {index} must be an object, "
            f"got {type(value).__name__}"
        )
    for field_name in _REQUIRED_FIELDS:
        if field_name not in value:
            raise EvalCorpusError(
                f"eval corpus record {index} missing required field {field_name}"
            )
        field_value = value[field_name]
        if not isinstance(field_value, str) or not field_value.strip():
            raise EvalCorpusError(
                f"eval corpus record {index} field {field_name} must be a "
                "non-blank string"
            )
    return value
