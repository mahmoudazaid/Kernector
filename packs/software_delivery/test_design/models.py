"""Pack-local draft models for the Software Delivery test-design workflow."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from domain.knowledge import SourceReference
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.limits import (
    MAX_AUTOMATION_RATIONALE_CHARS,
    MAX_CANDIDATES,
    MAX_EVIDENCE_FINGERPRINT_CHARS,
    MAX_EVIDENCE_REFS,
    MAX_EXPECTED_RESULT_CHARS,
    MAX_GHERKIN_CHARS,
    MAX_ID_CHARS,
    MAX_PRECONDITIONS_CHARS,
    MAX_RATIONALE_CHARS,
    MAX_STEP_CHARS,
    MAX_STEPS,
    MAX_TICKET_IDENTIFIER_CHARS,
    MAX_TITLE_CHARS,
)

CoverageCategory = Literal[
    "positive",
    "negative",
    "edge_case",
]
DraftStatus = Literal["coverage_review", "ready", "case_editing"]
CandidateOrigin = Literal["suggested", "manual"]
TestCaseType = Literal["manual", "cucumber"]
AutomationFit = Literal["applicable", "not_applicable", "unclear"]
CaseAvailability = Literal["available", "insufficient_evidence"]

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


DRAFT_STATUSES: frozenset[str] = frozenset(
    {"coverage_review", "ready", "case_editing"}
)
DRAFT_STATUSES_DISPLAY = str(sorted(DRAFT_STATUSES))

CANDIDATE_ORIGINS: frozenset[str] = frozenset({"suggested", "manual"})
CANDIDATE_ORIGINS_DISPLAY = str(sorted(CANDIDATE_ORIGINS))

TEST_CASE_TYPES: frozenset[str] = frozenset({"manual", "cucumber"})
TEST_CASE_TYPES_DISPLAY = str(sorted(TEST_CASE_TYPES))

AUTOMATION_FITS: frozenset[str] = frozenset(
    {"applicable", "not_applicable", "unclear"}
)
AUTOMATION_FITS_DISPLAY = str(sorted(AUTOMATION_FITS))

CASE_AVAILABILITIES: frozenset[str] = frozenset(
    {"available", "insufficient_evidence"}
)
CASE_AVAILABILITIES_DISPLAY = str(sorted(CASE_AVAILABILITIES))

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


def _require_optional_bounded_text(
    value: object,
    field_name: str,
    max_chars: int,
) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TestDesignValidationError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if len(value) > max_chars:
        raise TestDesignValidationError(
            f"{field_name} must be at most {max_chars} characters, got {len(value)}"
        )
    return value


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


def _require_allowlist(
    value: object,
    field_name: str,
    allowed: frozenset[str],
    display: str,
) -> str:
    if not isinstance(value, str):
        raise TestDesignValidationError(
            f"{field_name} must be one of {display}, got {type(value).__name__}"
        )
    if value not in allowed:
        raise TestDesignValidationError(f"{field_name} must be one of {display}")
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


def _normalize_test_type(value: object) -> str | None:
    if value is None:
        return None
    return _require_allowlist(
        value, "test_type", TEST_CASE_TYPES, TEST_CASE_TYPES_DISPLAY
    )


def _normalize_steps(value: object) -> tuple[str, ...]:
    steps = _require_sequence(value, "steps")
    if len(steps) > MAX_STEPS:
        raise TestDesignValidationError(
            f"steps must have at most {MAX_STEPS} items, got {len(steps)}"
        )
    normalized: list[str] = []
    for index, step in enumerate(steps):
        if not isinstance(step, str) or not step.strip():
            raise TestDesignValidationError(
                f"steps[{index}] must be a non-empty string"
            )
        if len(step) > MAX_STEP_CHARS:
            raise TestDesignValidationError(
                f"steps[{index}] must be at most {MAX_STEP_CHARS} characters, "
                f"got {len(step)}"
            )
        normalized.append(step)
    return tuple(normalized)


def coverage_candidate_fingerprint(candidate: TestCandidate) -> tuple[object, ...]:
    """Coverage identity fingerprint — excludes ``test_type`` (#300 demotion)."""
    refs = tuple(
        (ref.source_id, ref.source_type) for ref in candidate.evidence_references
    )
    return (
        candidate.candidate_id,
        candidate.title,
        candidate.category,
        candidate.rationale,
        candidate.selected,
        candidate.origin,
        refs,
    )


_SCENARIO_HEADER_KEYWORDS = (
    "scenario:",
    "scenario outline:",
    "scenario template:",
    "example:",
)
_BACKGROUND_HEADER_KEYWORDS = ("background:",)


def normalize_gherkin_steps(text: str, *, header_keywords: Sequence[str]) -> str:
    """Return step lines only: headers removed, indentation and blank lines stripped."""
    lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(tuple(header_keywords)):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def coverage_candidates_equal(
    left: Sequence[TestCandidate],
    right: Sequence[TestCandidate],
) -> bool:
    """Return True when coverage fingerprints match (ignoring test_type)."""
    if len(left) != len(right):
        return False
    for left_item, right_item in zip(left, right, strict=True):
        if coverage_candidate_fingerprint(left_item) != coverage_candidate_fingerprint(
            right_item
        ):
            return False
    return True


def is_deselection_only(
    previous: Sequence[TestCandidate],
    updated: Sequence[TestCandidate],
) -> bool:
    """Return True when the only coverage change is unselecting candidates."""
    if len(previous) != len(updated):
        return False
    changed = False
    for before, after in zip(previous, updated, strict=True):
        before_print = coverage_candidate_fingerprint(before)
        after_print = coverage_candidate_fingerprint(after)
        if before_print == after_print:
            continue
        if not (before.selected and not after.selected):
            return False
        if before_print[:4] + before_print[5:] != after_print[:4] + after_print[5:]:
            return False
        changed = True
    return changed


def is_title_only_change(
    previous: Sequence[TestCandidate],
    updated: Sequence[TestCandidate],
) -> bool:
    """Return True when the only change is renaming candidates (type unchanged)."""
    if len(previous) != len(updated):
        return False
    changed = False
    for before, after in zip(previous, updated, strict=True):
        before_print = coverage_candidate_fingerprint(before)
        after_print = coverage_candidate_fingerprint(after)
        if before_print[:1] + before_print[2:] != after_print[:1] + after_print[2:]:
            return False
        if before.test_type != after.test_type:
            return False
        if before.title != after.title:
            changed = True
    return changed


def keep_generated_cases_for_unchanged_candidates(
    cases: Sequence[GeneratedTestCase],
    *,
    previous: Sequence[TestCandidate],
    updated: Sequence[TestCandidate],
) -> tuple[GeneratedTestCase, ...]:
    """Keep cases whose candidate is still selected with identical coverage and type."""
    previous_by_id = {item.candidate_id: item for item in previous}
    updated_by_id = {item.candidate_id: item for item in updated}
    kept: list[GeneratedTestCase] = []
    for case in cases:
        before = previous_by_id.get(case.candidate_id)
        after = updated_by_id.get(case.candidate_id)
        if before is None or after is None or not after.selected:
            continue
        if coverage_candidate_fingerprint(before) != coverage_candidate_fingerprint(
            after
        ):
            continue
        if before.test_type != after.test_type:
            continue
        kept.append(case)
    return tuple(kept)


def drop_generated_cases_for_type_changes(
    cases: Sequence[GeneratedTestCase],
    *,
    previous: Sequence[TestCandidate],
    updated: Sequence[TestCandidate],
) -> tuple[GeneratedTestCase, ...]:
    """Drop generated cases whose candidate ``test_type`` changed."""
    previous_types: Mapping[str, str | None] = {
        item.candidate_id: item.test_type for item in previous
    }
    updated_types: Mapping[str, str | None] = {
        item.candidate_id: item.test_type for item in updated
    }
    kept: list[GeneratedTestCase] = []
    for case in cases:
        if previous_types.get(case.candidate_id) != updated_types.get(
            case.candidate_id
        ):
            continue
        kept.append(case)
    return tuple(kept)


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
    test_type: TestCaseType | None = None

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
        object.__setattr__(self, "test_type", _normalize_test_type(self.test_type))


@dataclass(frozen=True, slots=True)
class GeneratedTestCase:
    """Detailed manual or Cucumber artifact for one selected candidate (#300)."""

    __test__ = False

    candidate_id: str
    test_type: TestCaseType
    automation_fit: AutomationFit
    automation_rationale: str
    availability: CaseAvailability
    preconditions: str
    steps: Sequence[str]
    expected_result: str
    gherkin: str
    user_edited: bool

    def __post_init__(self) -> None:
        _require_bounded_text(self.candidate_id, "candidate_id", MAX_ID_CHARS)
        object.__setattr__(
            self,
            "test_type",
            _require_allowlist(
                self.test_type, "test_type", TEST_CASE_TYPES, TEST_CASE_TYPES_DISPLAY
            ),
        )
        object.__setattr__(
            self,
            "automation_fit",
            _require_allowlist(
                self.automation_fit,
                "automation_fit",
                AUTOMATION_FITS,
                AUTOMATION_FITS_DISPLAY,
            ),
        )
        object.__setattr__(
            self,
            "automation_rationale",
            _require_optional_bounded_text(
                self.automation_rationale,
                "automation_rationale",
                MAX_AUTOMATION_RATIONALE_CHARS,
            ),
        )
        object.__setattr__(
            self,
            "availability",
            _require_allowlist(
                self.availability,
                "availability",
                CASE_AVAILABILITIES,
                CASE_AVAILABILITIES_DISPLAY,
            ),
        )
        _require_bool(self.user_edited, "user_edited")

        preconditions = _require_optional_bounded_text(
            self.preconditions, "preconditions", MAX_PRECONDITIONS_CHARS
        )
        steps = _normalize_steps(self.steps)
        expected_result = _require_optional_bounded_text(
            self.expected_result, "expected_result", MAX_EXPECTED_RESULT_CHARS
        )
        gherkin = normalize_gherkin_steps(
            _require_optional_bounded_text(self.gherkin, "gherkin", MAX_GHERKIN_CHARS),
            header_keywords=_SCENARIO_HEADER_KEYWORDS,
        )

        if self.availability == "insufficient_evidence":
            if preconditions or steps or expected_result or gherkin:
                raise TestDesignValidationError(
                    "insufficient_evidence cases must not invent steps or Gherkin"
                )
            object.__setattr__(self, "preconditions", "")
            object.__setattr__(self, "steps", ())
            object.__setattr__(self, "expected_result", "")
            object.__setattr__(self, "gherkin", "")
            return

        if self.test_type == "manual":
            if gherkin.strip():
                raise TestDesignValidationError(
                    "gherkin must be empty for available manual cases"
                )
            object.__setattr__(
                self,
                "preconditions",
                _require_optional_bounded_text(
                    preconditions, "preconditions", MAX_PRECONDITIONS_CHARS
                ),
            )
            if not steps:
                raise TestDesignValidationError(
                    "steps must be non-empty for available manual cases"
                )
            if not expected_result.strip():
                raise TestDesignValidationError(
                    "expected_result must be non-empty for available manual cases"
                )
            object.__setattr__(self, "steps", steps)
            object.__setattr__(self, "expected_result", expected_result)
            object.__setattr__(self, "gherkin", "")
            return

        if preconditions.strip():
            raise TestDesignValidationError(
                "preconditions must be empty for available cucumber cases"
            )
        if steps:
            raise TestDesignValidationError(
                "steps must be empty for available cucumber cases"
            )
        if expected_result.strip():
            raise TestDesignValidationError(
                "expected_result must be empty for available cucumber cases"
            )
        object.__setattr__(self, "preconditions", "")
        object.__setattr__(self, "steps", ())
        object.__setattr__(self, "expected_result", "")
        object.__setattr__(
            self,
            "gherkin",
            _require_bounded_text(gherkin, "gherkin", MAX_GHERKIN_CHARS),
        )


@dataclass(frozen=True, slots=True)
class TestCoverageDraft:
    """Workspace-scoped interactive coverage and case-editing draft.

    Status ``ready`` means coverage selection is confirmed. Status
    ``case_editing`` means detailed cases exist or are being edited (#300).
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
    generated_cases: Sequence[GeneratedTestCase] = ()
    evidence_fingerprint: str | None = None
    cucumber_feature: str = ""
    cucumber_background: str = ""

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

        fingerprint = self.evidence_fingerprint
        if fingerprint is not None:
            object.__setattr__(
                self,
                "evidence_fingerprint",
                _require_bounded_text(
                    fingerprint,
                    "evidence_fingerprint",
                    MAX_EVIDENCE_FINGERPRINT_CHARS,
                ),
            )

        selected_ids = {
            candidate.candidate_id
            for candidate in normalized_candidates
            if candidate.selected
        }
        generated = _require_sequence(self.generated_cases, "generated_cases")
        seen_case_ids: set[str] = set()
        normalized_cases: list[GeneratedTestCase] = []
        for item in generated:
            if not isinstance(item, GeneratedTestCase):
                raise TestDesignValidationError(
                    "generated_cases items must be GeneratedTestCase, "
                    f"got {type(item).__name__}"
                )
            if item.candidate_id in seen_case_ids:
                raise TestDesignValidationError(
                    "generated_cases items must have unique candidate_id"
                )
            if item.candidate_id not in selected_ids:
                raise TestDesignValidationError(
                    "generated_cases candidate_id must reference a selected candidate"
                )
            seen_case_ids.add(item.candidate_id)
            normalized_cases.append(item)
        object.__setattr__(self, "generated_cases", tuple(normalized_cases))

        object.__setattr__(
            self,
            "cucumber_feature",
            _require_optional_bounded_text(
                self.cucumber_feature, "cucumber_feature", MAX_TITLE_CHARS
            ),
        )
        object.__setattr__(
            self,
            "cucumber_background",
            normalize_gherkin_steps(
                _require_optional_bounded_text(
                    self.cucumber_background, "cucumber_background", MAX_GHERKIN_CHARS
                ),
                header_keywords=_BACKGROUND_HEADER_KEYWORDS,
            ),
        )

    @property
    def selected_candidate_ids(self) -> tuple[str, ...]:
        """Stable ids of candidates currently selected for coverage confirm."""
        return tuple(
            candidate.candidate_id
            for candidate in self.candidates
            if candidate.selected
        )
