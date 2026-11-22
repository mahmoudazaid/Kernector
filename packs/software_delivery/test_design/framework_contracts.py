"""Framework-aware Test Design contracts (#368).

Vocabulary (must stay distinct):
- Specification syntax: how behaviour is written (e.g. Gherkin, none).
- Test framework: what executes tests (e.g. robot_framework, playwright).
- Test type: who/what runs the case (``manual`` or ``cucumber``).

``test_type=cucumber`` means a BDD scenario written in Gherkin. It does not
promise a Cucumber (or SpecFlow/Behave) runtime.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from packs.software_delivery.project_profile.models import (
    Convention,
    ReusableComponent,
)
from packs.software_delivery.test_design.errors import TestDesignValidationError
from packs.software_delivery.test_design.limits import (
    MAX_EVIDENCE_FINGERPRINT_CHARS,
    MAX_ID_CHARS,
)

StepReuseOutcome = Literal[
    "reused",
    "ambiguous",
    "implementation_required",
    "unsupported",
]
FrameworkResultStatus = Literal[
    "ok",
    "framework_choice_required",
    "profile_required",
    "unsupported_framework",
]
FrameworkEvidenceOrigin = Literal["client_supplied"]

STEP_REUSE_OUTCOMES: frozenset[str] = frozenset(
    {"reused", "ambiguous", "implementation_required", "unsupported"}
)
FRAMEWORK_RESULT_STATUSES: frozenset[str] = frozenset(
    {
        "ok",
        "framework_choice_required",
        "profile_required",
        "unsupported_framework",
    }
)
FRAMEWORK_EVIDENCE_ORIGINS: frozenset[str] = frozenset({"client_supplied"})

MVP_FRAMEWORK_ID = "robot_framework"


def _require_bounded_text(value: object, field_name: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise TestDesignValidationError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    stripped = value.strip()
    if not stripped:
        raise TestDesignValidationError(f"{field_name} must be non-empty")
    if len(stripped) > max_chars:
        raise TestDesignValidationError(
            f"{field_name} must be at most {max_chars} characters"
        )
    return stripped


@dataclass(frozen=True, slots=True)
class FrameworkSelection:
    """Confirmed framework choice stored on a Test Design draft.

    Holds a bounded snapshot of conventions and reusable components from the
    recomputed #387 profile. Raw profile evidence is not stored here.
    """

    component_id: str
    framework_id: str
    profile_fingerprint: str
    evidence_origin: FrameworkEvidenceOrigin
    conventions: tuple[Convention, ...]
    reusable_components: tuple[ReusableComponent, ...]
    confirmed_at_version: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "component_id",
            _require_bounded_text(self.component_id, "component_id", MAX_ID_CHARS),
        )
        object.__setattr__(
            self,
            "framework_id",
            _require_bounded_text(self.framework_id, "framework_id", MAX_ID_CHARS),
        )
        object.__setattr__(
            self,
            "profile_fingerprint",
            _require_bounded_text(
                self.profile_fingerprint,
                "profile_fingerprint",
                MAX_EVIDENCE_FINGERPRINT_CHARS,
            ),
        )
        if self.evidence_origin not in FRAMEWORK_EVIDENCE_ORIGINS:
            raise TestDesignValidationError(
                "evidence_origin must be one of "
                f"{sorted(FRAMEWORK_EVIDENCE_ORIGINS)}"
            )
        if not isinstance(self.confirmed_at_version, int) or self.confirmed_at_version < 1:
            raise TestDesignValidationError(
                "confirmed_at_version must be a positive integer"
            )
        conventions = self.conventions
        if not isinstance(conventions, Sequence) or isinstance(
            conventions, (str, bytes)
        ):
            raise TestDesignValidationError("conventions must be a sequence")
        for item in conventions:
            if not isinstance(item, Convention):
                raise TestDesignValidationError(
                    "conventions items must be Convention, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "conventions", tuple(conventions))
        components = self.reusable_components
        if not isinstance(components, Sequence) or isinstance(components, (str, bytes)):
            raise TestDesignValidationError("reusable_components must be a sequence")
        for item in components:
            if not isinstance(item, ReusableComponent):
                raise TestDesignValidationError(
                    "reusable_components items must be ReusableComponent, "
                    f"got {type(item).__name__}"
                )
        object.__setattr__(self, "reusable_components", tuple(components))


@dataclass(frozen=True, slots=True)
class FrameworkFile:
    """One generated file following the #359 safe path contract."""

    filename: str
    suggested_path: str
    content: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "filename",
            _require_bounded_text(self.filename, "filename", MAX_ID_CHARS),
        )
        object.__setattr__(
            self,
            "suggested_path",
            _require_bounded_text(self.suggested_path, "suggested_path", 512),
        )
        if not isinstance(self.content, str):
            raise TestDesignValidationError("content must be a string")
        if ".." in self.suggested_path.replace("\\", "/").split("/"):
            raise TestDesignValidationError(
                "suggested_path must be a safe relative path"
            )
        if self.suggested_path.startswith("/") or self.suggested_path.startswith("\\"):
            raise TestDesignValidationError(
                "suggested_path must be a relative path"
            )


@dataclass(frozen=True, slots=True)
class StepOutcome:
    """Reuse decision for one generated step."""

    step: str
    outcome: StepReuseOutcome
    behaviour_refs: tuple[tuple[str, str], ...]
    convention_refs: tuple[str, ...]
    component_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "step", _require_bounded_text(self.step, "step", 500)
        )
        if self.outcome not in STEP_REUSE_OUTCOMES:
            raise TestDesignValidationError(
                f"outcome must be one of {sorted(STEP_REUSE_OUTCOMES)}"
            )
        object.__setattr__(self, "behaviour_refs", tuple(self.behaviour_refs))
        object.__setattr__(self, "convention_refs", tuple(self.convention_refs))


@dataclass(frozen=True, slots=True)
class FrameworkTestTrace:
    """Traceability for one generated framework test."""

    candidate_id: str
    evidence_refs: tuple[tuple[str, str], ...]
    step_outcomes: tuple[StepOutcome, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "candidate_id",
            _require_bounded_text(self.candidate_id, "candidate_id", MAX_ID_CHARS),
        )
        object.__setattr__(self, "evidence_refs", tuple(self.evidence_refs))
        object.__setattr__(self, "step_outcomes", tuple(self.step_outcomes))


@dataclass(frozen=True, slots=True)
class FrameworkArtifactResult:
    """Typed result of framework-aware generation (#368)."""

    status: FrameworkResultStatus
    framework_id: str
    files: tuple[FrameworkFile, ...]
    tests: tuple[FrameworkTestTrace, ...]
    implementation_required: tuple[str, ...]
    skipped: tuple[str, ...]
    untrusted_model_output: bool
    evidence_origin: FrameworkEvidenceOrigin

    def __post_init__(self) -> None:
        if self.status not in FRAMEWORK_RESULT_STATUSES:
            raise TestDesignValidationError(
                f"status must be one of {sorted(FRAMEWORK_RESULT_STATUSES)}"
            )
        object.__setattr__(
            self,
            "framework_id",
            _require_bounded_text(self.framework_id, "framework_id", MAX_ID_CHARS)
            if self.framework_id
            else self.framework_id,
        )
        if self.status == "unsupported_framework" and self.files:
            raise TestDesignValidationError(
                "unsupported_framework results must not include files"
            )
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "tests", tuple(self.tests))
        object.__setattr__(
            self, "implementation_required", tuple(self.implementation_required)
        )
        object.__setattr__(self, "skipped", tuple(self.skipped))
        if not isinstance(self.untrusted_model_output, bool):
            raise TestDesignValidationError(
                "untrusted_model_output must be a boolean"
            )
        if self.evidence_origin not in FRAMEWORK_EVIDENCE_ORIGINS:
            raise TestDesignValidationError(
                "evidence_origin must be one of "
                f"{sorted(FRAMEWORK_EVIDENCE_ORIGINS)}"
            )
