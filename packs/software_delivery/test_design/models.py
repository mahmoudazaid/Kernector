"""Pack-local draft models for the Software Delivery test-design workflow."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.limits import (
    MAX_CANDIDATES,
    MAX_EVIDENCE_REFS,
    MAX_ID_CHARS,
    MAX_RATIONALE_CHARS,
    MAX_TICKET_IDENTIFIER_CHARS,
    MAX_TITLE_CHARS,
)

CoverageCategory = Literal[
    "positive",
    "negative",
    "edge_case",
]
DraftStatus = Literal["coverage_review", "ready"]
CandidateOrigin = Literal["suggested", "manual"]

COVERAGE_CATEGORIES: frozenset[str] = frozenset(
    {
        "positive",
        "negative",
        "edge_case",
    }
)
COVERAGE_CATEGORIES_DISPLAY = str(sorted(COVERAGE_CATEGORIES))

# Common model / legacy labels → canonical CoverageCategory.
_CATEGORY_ALIASES: dict[str, str] = {
    "happy_path": "positive",
    "happy": "positive",
    "integration": "positive",
    "permission_security": "negative",
    "security": "negative",
    "auth": "negative",
    "failure_recovery": "edge_case",
    "edge": "edge_case",
    "edgecase": "edge_case",
}


def coerce_coverage_category(raw: object) -> str | None:
    """Return a canonical coverage category, or ``None`` if unrecoverable."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower().replace(" ", "_").replace("-", "_")
    if not value:
        return None
    if value in COVERAGE_CATEGORIES:
        return value
    return _CATEGORY_ALIASES.get(value)


DRAFT_STATUSES: frozenset[str] = frozenset({"coverage_review", "ready"})
DRAFT_STATUSES_DISPLAY = str(sorted(DRAFT_STATUSES))

CANDIDATE_ORIGINS: frozenset[str] = frozenset({"suggested", "manual"})
CANDIDATE_ORIGINS_DISPLAY = str(sorted(CANDIDATE_ORIGINS))

_BARE_TICKET_ID = re.compile(r"^\d+$")
_E = TypeVar("_E", bound=Exception)


def _require_text(
    value: object,
    field_name: str,
    error_type: type[_E] = TestDesignValidationError,
) -> str:
    if not isinstance(value, str):
        raise error_type(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    if not value.strip():
        raise error_type(f"{field_name} must be non-empty")
    return value


def _require_bounded_text(
    value: object,
    field_name: str,
    max_chars: int,
    error_type: type[_E] = TestDesignValidationError,
) -> str:
    text = _require_text(value, field_name, error_type)
    if len(text) > max_chars:
        raise error_type(
            f"{field_name} must be at most {max_chars} characters, got {len(text)}"
        )
    return text


def _require_sequence(
    value: object,
    field_name: str,
    error_type: type[_E] = TestDesignValidationError,
) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise error_type(f"{field_name} must be a sequence, got {type(value).__name__}")
    return value


def _require_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise TestDesignValidationError(
            f"{field_name} must be a bool, got {type(value).__name__}"
        )
    return value


def _require_positive_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TestDesignValidationError(
            f"{field_name} must be a positive integer, got {type(value).__name__}"
        )
    if value <= 0:
        raise TestDesignValidationError(
            f"{field_name} must be a positive integer, got {value}"
        )
    return value


def _require_category(value: object, field_name: str = "category") -> str:
    if not isinstance(value, str):
        raise TestDesignValidationError(
            f"{field_name} must be one of {COVERAGE_CATEGORIES_DISPLAY}, "
            f"got {type(value).__name__}"
        )
    if value not in COVERAGE_CATEGORIES:
        raise TestDesignValidationError(
            f"{field_name} must be one of {COVERAGE_CATEGORIES_DISPLAY}"
        )
    return value


def _sorted_unique_references(
    references: Sequence[SourceReference],
) -> tuple[SourceReference, ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[SourceReference] = []
    for ref in references:
        key = (ref.source_type, ref.source_id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return tuple(sorted(unique, key=lambda ref: (ref.source_type, ref.source_id)))


def _normalize_references(
    value: object,
    *,
    field_name: str = "evidence_references",
    allow_empty: bool = False,
) -> tuple[SourceReference, ...]:
    refs = _require_sequence(value, field_name)
    if len(refs) == 0:
        if allow_empty:
            return ()
        raise TestDesignValidationError(f"{field_name} must be non-empty")
    if len(refs) > MAX_EVIDENCE_REFS:
        raise TestDesignValidationError(
            f"{field_name} must have at most {MAX_EVIDENCE_REFS} items, "
            f"got {len(refs)}"
        )
    normalized: list[SourceReference] = []
    for ref in refs:
        if not isinstance(ref, SourceReference):
            raise TestDesignValidationError(
                f"{field_name} items must be SourceReference, "
                f"got {type(ref).__name__}"
            )
        normalized.append(ref)
    return _sorted_unique_references(normalized)


def _require_ticket_identifier(value: object) -> str:
    text = _require_bounded_text(
        value, "ticket_identifier", MAX_TICKET_IDENTIFIER_CHARS
    )
    if _BARE_TICKET_ID.fullmatch(text.strip()):
        raise TestDesignValidationError(
            "ticket_identifier must not be a bare number"
        )
    return text


@dataclass(frozen=True, slots=True)
class TestCandidate:
    """One suggested or manually added coverage candidate."""

    __test__ = False

    candidate_id: str
    title: str
    category: CoverageCategory
    rationale: str
    evidence_references: Sequence[SourceReference]
    selected: bool
    origin: CandidateOrigin

    def __post_init__(self) -> None:
        _require_bounded_text(self.candidate_id, "candidate_id", MAX_ID_CHARS)
        _require_bounded_text(self.title, "title", MAX_TITLE_CHARS)
        _require_category(self.category)
        _require_bounded_text(self.rationale, "rationale", MAX_RATIONALE_CHARS)
        _require_bool(self.selected, "selected")
        if not isinstance(self.origin, str):
            raise TestDesignValidationError(
                f"origin must be one of {CANDIDATE_ORIGINS_DISPLAY}, "
                f"got {type(self.origin).__name__}"
            )
        if self.origin not in CANDIDATE_ORIGINS:
            raise TestDesignValidationError(
                f"origin must be one of {CANDIDATE_ORIGINS_DISPLAY}"
            )
        object.__setattr__(
            self,
            "evidence_references",
            _normalize_references(
                self.evidence_references,
                allow_empty=self.origin == "manual",
            ),
        )


@dataclass(frozen=True, slots=True)
class TestCoverageDraft:
    """Workspace-scoped interactive coverage-candidate draft.

    Status ``ready`` means coverage selection is confirmed — not that detailed
    test cases have been generated (#300).
    """

    __test__ = False

    draft_id: str
    workspace_id: str
    conversation_id: str
    source_reference: SourceReference
    ticket_identifier: str
    status: DraftStatus
    candidates: Sequence[TestCandidate]
    version: int

    def __post_init__(self) -> None:
        _require_bounded_text(self.draft_id, "draft_id", MAX_ID_CHARS)
        _require_bounded_text(self.workspace_id, "workspace_id", MAX_ID_CHARS)
        _require_bounded_text(self.conversation_id, "conversation_id", MAX_ID_CHARS)
        if not isinstance(self.source_reference, SourceReference):
            raise TestDesignValidationError(
                "source_reference must be a SourceReference, "
                f"got {type(self.source_reference).__name__}"
            )
        object.__setattr__(
            self, "ticket_identifier", _require_ticket_identifier(self.ticket_identifier)
        )
        if not isinstance(self.status, str):
            raise TestDesignValidationError(
                f"status must be one of {DRAFT_STATUSES_DISPLAY}, "
                f"got {type(self.status).__name__}"
            )
        if self.status not in DRAFT_STATUSES:
            raise TestDesignValidationError(
                f"status must be one of {DRAFT_STATUSES_DISPLAY}"
            )
        _require_positive_int(self.version, "version")

        candidates = _require_sequence(self.candidates, "candidates")
        if len(candidates) > MAX_CANDIDATES:
            raise TestDesignValidationError(
                f"candidates must have at most {MAX_CANDIDATES} items, "
                f"got {len(candidates)}"
            )
        seen_candidate_ids: set[str] = set()
        normalized_candidates: list[TestCandidate] = []
        for item in candidates:
            if not isinstance(item, TestCandidate):
                raise TestDesignValidationError(
                    "candidates items must be TestCandidate, "
                    f"got {type(item).__name__}"
                )
            if item.candidate_id in seen_candidate_ids:
                raise TestDesignValidationError(
                    "candidates items must have unique candidate_id"
                )
            seen_candidate_ids.add(item.candidate_id)
            normalized_candidates.append(item)
        object.__setattr__(self, "candidates", tuple(normalized_candidates))

    @property
    def selected_candidate_ids(self) -> tuple[str, ...]:
        """Stable ids of candidates currently selected for coverage confirm."""
        return tuple(
            candidate.candidate_id
            for candidate in self.candidates
            if candidate.selected
        )
