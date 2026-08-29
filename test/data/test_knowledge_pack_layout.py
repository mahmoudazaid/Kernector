"""Example-pack layout: Story Intelligence corpus under packs/, not root."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIR = REPO_ROOT / "data" / "knowledge"
ROOT_CORPUS = KNOWLEDGE_DIR / "documents.json"
STORY_INTELLIGENCE_PACK = (
    KNOWLEDGE_DIR / "packs" / "story-intelligence" / "documents.json"
)

SDLC_DOC_TYPES = frozenset(
    {"openapi", "user_story", "bug", "source_code", "srs", "qa_guidance"}
)
STORY_INTELLIGENCE_SOURCE_IDS = frozenset(
    {
        "openapi-payments-001",
        "story-checkout-001",
        "bug-auth-001",
        "code-ingest-001",
        "srs-auth-001",
        "qa-sev-001",
    }
)


def _load_doc_types(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return {document["doc_type"] for document in payload}


def _load_source_ids(path: Path) -> set[str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    return {document["source_id"] for document in payload}


def test_story_intelligence_examples_live_under_pack_not_root() -> None:
    assert STORY_INTELLIGENCE_PACK.is_file()
    assert ROOT_CORPUS.is_file()

    root_types = _load_doc_types(ROOT_CORPUS)
    pack_types = _load_doc_types(STORY_INTELLIGENCE_PACK)
    pack_ids = _load_source_ids(STORY_INTELLIGENCE_PACK)

    assert root_types & SDLC_DOC_TYPES == set()
    assert SDLC_DOC_TYPES <= pack_types
    assert STORY_INTELLIGENCE_SOURCE_IDS <= pack_ids
