"""Domain entities and value objects."""

from dataclasses import dataclass, field
from typing import Literal

from domain.errors import DomainValidationError

Role = Literal["system", "user", "assistant"]
_VALID_ROLES = frozenset({"system", "user", "assistant"})
_VALID_ROLES_DISPLAY = str(sorted(_VALID_ROLES))


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, str):
            raise DomainValidationError(
                f"role must be one of {_VALID_ROLES_DISPLAY}, "
                f"got {type(self.role).__name__}"
            )
        if self.role not in _VALID_ROLES:
            raise DomainValidationError(
                f"role must be one of {_VALID_ROLES_DISPLAY}"
            )
        if not isinstance(self.content, str):
            raise DomainValidationError(
                f"content must be a non-empty string, got {type(self.content).__name__}"
            )
        if not self.content.strip():
            raise DomainValidationError("content must be non-empty")


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None


@dataclass(frozen=True, slots=True)
class AskResult:
    content: str
    model: str | None = None
    latency_ms: int | None = None
    usage: Usage | None = None
    settings: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AgentTurnResult:
    """Final text from a tool-calling agent turn, plus optional step count."""

    content: str
    steps: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.content, str):
            raise DomainValidationError(
                f"content must be a non-empty string, got {type(self.content).__name__}"
            )
        if not self.content.strip():
            raise DomainValidationError("content must be non-empty")
        if self.steps is not None:
            if not isinstance(self.steps, int) or isinstance(self.steps, bool):
                raise DomainValidationError(
                    f"steps must be a non-negative integer, got {type(self.steps).__name__}"
                )
            if self.steps < 0:
                raise DomainValidationError(
                    f"steps must be a non-negative integer, got {self.steps}"
                )


@dataclass(frozen=True, slots=True)
class PromptVariant:
    key: str
    name: str
    description: str
    system: str
    off_topic_marker: str | None = None
    extra_reject_patterns: tuple[str, ...] = ()
