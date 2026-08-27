"""Ingest the configured knowledge corpus through the application use case.

Run with::

    uv run python -m presentation.cli.ingest

The command is source-agnostic: it consumes normalized ``SourceDocument``
values from composition and never branches on ``doc_type``.
"""

from __future__ import annotations

import sys

from application.contracts import IngestRequest
from application.errors import ApplicationValidationError, ConfigurationError
from composition import (
    KnowledgeLoadError,
    build_ingest_knowledge,
    load_knowledge_documents,
    load_runtime_settings,
)


def main() -> int:
    """Load the corpus, run ingestion, and report counts.

    Returns:
        int: ``0`` on success, ``1`` for corpus/ingestion failure, ``2`` for
        configuration failure.
    """
    try:
        settings = load_runtime_settings()
        documents = load_knowledge_documents(settings)
        use_case = build_ingest_knowledge(settings)
        response = use_case.execute(IngestRequest(documents=documents))
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (KnowledgeLoadError, ApplicationValidationError) as error:
        print(str(error), file=sys.stderr)
        return 1

    print(f"accepted_documents={len(response.accepted_ids)}")
    print(f"chunk_count={response.chunk_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
