"""Submit and clear response feedback (#219)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from application.errors import InputRejectedError
from domain.ports import ResponseFeedbackRepository, RunProvenanceLookup
from domain.response_feedback import (
    FEEDBACK_RATINGS,
    FEEDBACK_RATINGS_DISPLAY,
    FEEDBACK_REASONS,
    FEEDBACK_REASONS_DISPLAY,
    MAX_FEEDBACK_COMMENT_LENGTH,
    FeedbackRating,
    FeedbackReason,
    ResponseFeedback,
    RunProvenance,
)


class FeedbackNotFoundError(Exception):
    """No feedback exists for the given request_id in this workspace."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        super().__init__("No feedback found for this response.")


@dataclass(frozen=True, slots=True)
class UpsertFeedbackRequest:
    """Client-supplied fields for creating or updating a rating."""

    request_id: str
    rating: FeedbackRating
    conversation_id: str | None = None
    client_message_id: str | None = None
    reason: FeedbackReason | None = None
    comment: str | None = None


@dataclass(frozen=True, slots=True)
class ClearFeedbackRequest:
    """Client-supplied identity for clearing a rating."""

    request_id: str


class NullRunProvenanceLookup:
    """Default lookup until a trusted run ledger exists."""

    def get(self, request_id: str) -> RunProvenance | None:
        return None


class SubmitResponseFeedback:
    """Validate and upsert a thumbs rating via ``ResponseFeedbackRepository``."""

    def __init__(
        self,
        *,
        repository: ResponseFeedbackRepository,
        provenance: RunProvenanceLookup | None = None,
        workspace_id: str,
    ) -> None:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        self._repository = repository
        self._provenance = (
            provenance if provenance is not None else NullRunProvenanceLookup()
        )
        self._workspace_id = workspace_id.strip()

    def execute(self, request: UpsertFeedbackRequest) -> ResponseFeedback:
        request_id = _require_text(request.request_id, "request_id")
        if request.rating not in FEEDBACK_RATINGS:
            raise InputRejectedError(
                f"rating must be one of {FEEDBACK_RATINGS_DISPLAY}"
            )
        reason = request.reason
        if reason is not None:
            if request.rating != "negative":
                raise InputRejectedError(
                    "reason is only allowed when rating is negative"
                )
            if reason not in FEEDBACK_REASONS:
                raise InputRejectedError(
                    f"reason must be one of {FEEDBACK_REASONS_DISPLAY}"
                )
        comment = _optional_comment(request.comment)
        conversation_id = _optional_text(request.conversation_id)
        client_message_id = _optional_text(request.client_message_id)

        provenance = self._provenance.get(request_id)
        now = _utc_now()
        feedback = ResponseFeedback(
            workspace_id=self._workspace_id,
            request_id=request_id,
            rating=request.rating,
            created_at=now,
            updated_at=now,
            conversation_id=_first_non_empty(
                provenance.conversation_id if provenance else None,
                conversation_id,
            ),
            client_message_id=client_message_id,
            run_id=provenance.run_id if provenance else None,
            reason=reason,
            comment=comment,
            prompt_key=provenance.prompt_key if provenance else None,
            prompt_version=provenance.prompt_version if provenance else None,
            model=provenance.model if provenance else None,
            tools=provenance.tools if provenance else (),
        )
        return self._repository.upsert(feedback)


class ClearResponseFeedback:
    """Delete a thumbs rating via ``ResponseFeedbackRepository``."""

    def __init__(self, *, repository: ResponseFeedbackRepository) -> None:
        self._repository = repository

    def execute(self, request: ClearFeedbackRequest) -> None:
        request_id = _require_text(request.request_id, "request_id")
        if not self._repository.delete(request_id):
            raise FeedbackNotFoundError(request_id)


@dataclass(frozen=True, slots=True)
class GetFeedbackRequest:
    """Client-supplied identity for reading a rating."""

    request_id: str


class GetResponseFeedback:
    """Load a thumbs rating via ``ResponseFeedbackRepository``."""

    def __init__(self, *, repository: ResponseFeedbackRepository) -> None:
        self._repository = repository

    def execute(self, request: GetFeedbackRequest) -> ResponseFeedback:
        request_id = _require_text(request.request_id, "request_id")
        stored = self._repository.get(request_id)
        if stored is None:
            raise FeedbackNotFoundError(request_id)
        return stored


def _require_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputRejectedError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputRejectedError("optional text fields must be strings")
    stripped = value.strip()
    return stripped or None


def _optional_comment(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InputRejectedError("comment must be a string")
    if len(value) > MAX_FEEDBACK_COMMENT_LENGTH:
        raise InputRejectedError(
            f"comment must be at most {MAX_FEEDBACK_COMMENT_LENGTH} characters"
        )
    return value


def _first_non_empty(*values: str | None) -> str | None:
    for value in values:
        if value is not None and value.strip():
            return value.strip()
    return None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
