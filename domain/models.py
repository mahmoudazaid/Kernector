"""Domain entities and value objects."""

from dataclasses import dataclass, field
from typing import Literal

Role = Literal["system", "user", "assistant"]

@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str

@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None

@dataclass(frozen=True, slots=True)
class AskResult:
    content: str
    model: str|None = None
    latency_ms: int|None = None
    usage: Usage|None = None
    settings: dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class PromptVariant:
    key: str
    name: str
    description: str
    system: str
    off_topic_marker: str | None = None
