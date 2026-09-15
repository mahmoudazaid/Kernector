"""Outbound artifact contracts for provider-neutral uploads."""

from __future__ import annotations

from dataclasses import dataclass

from domain.errors import DomainValidationError


def _require_text(value: object, field_name: str) -> None:
    if not isinstance(value, str):
        raise DomainValidationError(
            f"{field_name} must be a non-empty string, got {type(value).__name__}"
        )
    if not value.strip():
        raise DomainValidationError(f"{field_name} must be non-empty")


@dataclass(frozen=True, slots=True)
class Artifact:
    """Bytes plus presentation metadata for an outbound upload."""

    file_name: str
    media_type: str
    content: bytes

    def __post_init__(self) -> None:
        _require_text(self.file_name, "file_name")
        _require_text(self.media_type, "media_type")
        if not isinstance(self.content, (bytes, bytearray)):
            raise DomainValidationError(
                f"content must be bytes, got {type(self.content).__name__}"
            )


@dataclass(frozen=True, slots=True)
class ArtifactReceipt:
    """Safe upload acknowledgment without provider secrets or payload bodies."""

    artifact_id: str
    file_name: str

    def __post_init__(self) -> None:
        _require_text(self.artifact_id, "artifact_id")
        _require_text(self.file_name, "file_name")
