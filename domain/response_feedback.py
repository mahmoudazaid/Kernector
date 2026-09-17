"""Response feedback contracts for thumbs up/down collection (#219)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

FeedbackRating = Literal["positive", "negative"]
FeedbackReason = Literal[
    "incorrect",
    "incomplete",
    "unsupported",
    "irrelevant",
    "wrong_tool",
    "unclear",
    "unsafe",
    "other",
]

FEEDBACK_RATINGS: frozenset[str] = frozenset({"positive", "negative"})
FEEDBACK_RATINGS_DISPLAY = str(sorted(FEEDBACK_RATINGS))
FEEDBACK_REASONS: frozenset[str] = frozenset(
    {
        "incorrect",
        "incomplete",
        "unsupported",
        "irrelevant",
        "wrong_tool",
        "unclear",
        "unsafe",
        "other",
    }
)
FEEDBACK_REASONS_DISPLAY = str(sorted(FEEDBACK_REASONS))
MAX_FEEDBACK_COMMENT_LENGTH = 2000


@dataclass(frozen=True, slots=True)
class ResponseFeedback:
    """One persisted rating for an assistant response.

    Identity is ``(workspace_id, request_id)``. ``client_message_id`` is optional
    UI correlation only. Prompt/model fields are nullable until a trusted run
    ledger supplies them.
    """

    workspace_id: str
    request_id: str
    rating: FeedbackRating
    created_at: str
    updated_at: str
    conversation_id: str | None = None
    client_message_id: str | None = None
    run_id: str | None = None
    reason: FeedbackReason | None = None
    comment: str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    model: str | None = None
    tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("workspace_id", "request_id", "created_at", "updated_at"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")
        if self.rating not in FEEDBACK_RATINGS:
            raise ValueError(f"rating must be one of {FEEDBACK_RATINGS_DISPLAY}")
        if self.reason is not None:
            if self.rating != "negative":
                raise ValueError("reason is only allowed when rating is negative")
            if self.reason not in FEEDBACK_REASONS:
                raise ValueError(
                    f"reason must be one of {FEEDBACK_REASONS_DISPLAY}"
                )
        if self.comment is not None:
            if not isinstance(self.comment, str):
                raise ValueError("comment must be a string")
            if len(self.comment) > MAX_FEEDBACK_COMMENT_LENGTH:
                raise ValueError(
                    f"comment must be at most {MAX_FEEDBACK_COMMENT_LENGTH} characters"
                )
        if not isinstance(self.tools, tuple) or any(
            not isinstance(name, str) or not name.strip() for name in self.tools
        ):
            raise ValueError("tools must be a tuple of non-empty strings")


@dataclass(frozen=True, slots=True)
class RunProvenance:
    """Trusted server-side metadata for a completed ask, keyed by request_id."""

    request_id: str
    conversation_id: str | None = None
    run_id: str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    model: str | None = None
    tools: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.request_id, str) or not self.request_id.strip():
            raise ValueError("request_id must be a non-empty string")
        if not isinstance(self.tools, Sequence) or isinstance(self.tools, (str, bytes)):
            raise ValueError("tools must be a sequence of strings")
        object.__setattr__(
            self,
            "tools",
            tuple(
                name for name in self.tools if isinstance(name, str) and name.strip()
            ),
        )
