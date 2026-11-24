"""Artifact descriptor contracts (ADR 0011, #373).

Kinds and contexts are opaque tokens: validation checks shape only. Meaning
lives in packs and infrastructure extractors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from domain.artifact.errors import ArtifactInputError
from domain.knowledge import SourceReference

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]+")
_TOKEN = re.compile(r"[a-z][a-z0-9_]*")
_MAX_IDENTIFIER_LENGTH = 64
_MAX_TOKEN_LENGTH = 64
_MAX_TEXT_LENGTH = 512
_MAX_KEY_LENGTH = 256
_MAX_URL_LENGTH = 2048


def _require_token(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ArtifactInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if len(value) > _MAX_TOKEN_LENGTH or not _TOKEN.fullmatch(value):
        raise ArtifactInputError(
            f"{field_name} must fullmatch [a-z][a-z0-9_]* and be at most "
            f"{_MAX_TOKEN_LENGTH} characters"
        )
    return value


def _require_identifier(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ArtifactInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if len(value) > _MAX_IDENTIFIER_LENGTH or not _IDENTIFIER.fullmatch(value):
        raise ArtifactInputError(
            f"{field_name} must fullmatch [A-Za-z0-9_-]+ and be at most "
            f"{_MAX_IDENTIFIER_LENGTH} characters"
        )
    return value


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ArtifactInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise ArtifactInputError(f"{field_name} must be non-empty")
    if len(value) > _MAX_TEXT_LENGTH:
        raise ArtifactInputError(
            f"{field_name} must be at most {_MAX_TEXT_LENGTH} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ArtifactInputError(f"{field_name} must not contain control characters")
    return value


def _require_key(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ArtifactInputError(
            f"{field_name} must be a string, got {type(value).__name__}"
        )
    if not value.strip():
        raise ArtifactInputError(f"{field_name} must be non-empty")
    if len(value) > _MAX_KEY_LENGTH:
        raise ArtifactInputError(
            f"{field_name} must be at most {_MAX_KEY_LENGTH} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ArtifactInputError(f"{field_name} must not contain control characters")
    return value


def _require_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, field_name)


def _require_optional_url(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArtifactInputError(f"url must be a string, got {type(value).__name__}")
    if not value.strip():
        raise ArtifactInputError("url must be non-empty")
    if len(value) > _MAX_URL_LENGTH:
        raise ArtifactInputError(
            f"url must be at most {_MAX_URL_LENGTH} characters"
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ArtifactInputError("url must not contain control characters")
    return value


@dataclass(frozen=True, slots=True)
class ContextAssignment:
    """A project context assigned to an artifact with a classification reason."""

    context: str
    reason: str

    def __post_init__(self) -> None:
        _require_token(self.context, "context")
        _require_token(self.reason, "reason")


@dataclass(frozen=True, slots=True)
class ArtifactPart:
    """An addressable fragment of an artifact, such as an API operation."""

    kind: str
    part_key: str
    operation_id: str | None = None
    summary: str | None = None
    response_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_token(self.kind, "kind")
        _require_key(self.part_key, "part_key")
        if self.operation_id is not None:
            _require_key(self.operation_id, "operation_id")
        if self.summary is not None:
            _require_text(self.summary, "summary")
        if not isinstance(self.response_codes, tuple):
            raise ArtifactInputError(
                f"response_codes must be a tuple, got {type(self.response_codes).__name__}"
            )
        for code in self.response_codes:
            _require_key(code, "response_code")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Addresses a whole artifact or one of its parts."""

    reference: SourceReference
    part_key: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise ArtifactInputError(
                f"reference must be a SourceReference, got {type(self.reference).__name__}"
            )
        if self.part_key is not None:
            _require_key(self.part_key, "part_key")


@dataclass(frozen=True, slots=True)
class ArtifactDescriptor:
    """Catalog document plus derived kind, keys, contexts and parts."""

    reference: SourceReference
    revision: str
    kind: str
    contexts: tuple[ContextAssignment, ...] = ()
    component_ids: tuple[str, ...] = ()
    external_keys: tuple[str, ...] = ()
    parts: tuple[ArtifactPart, ...] = ()
    title: str | None = None
    url: str | None = None
    diagnostic: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.reference, SourceReference):
            raise ArtifactInputError(
                f"reference must be a SourceReference, got {type(self.reference).__name__}"
            )
        _require_text(self.revision, "revision")
        _require_token(self.kind, "kind")
        if not isinstance(self.contexts, tuple) or not all(
            isinstance(item, ContextAssignment) for item in self.contexts
        ):
            raise ArtifactInputError(
                "contexts must be a tuple of ContextAssignment"
            )
        if not isinstance(self.component_ids, tuple):
            raise ArtifactInputError(
                f"component_ids must be a tuple, got {type(self.component_ids).__name__}"
            )
        for component_id in self.component_ids:
            _require_identifier(component_id, "component_id")
        if len(set(self.component_ids)) != len(self.component_ids):
            raise ArtifactInputError("component_ids must not repeat")
        if not isinstance(self.external_keys, tuple):
            raise ArtifactInputError(
                f"external_keys must be a tuple, got {type(self.external_keys).__name__}"
            )
        for key in self.external_keys:
            _require_key(key, "external_key")
        if len(set(self.external_keys)) != len(self.external_keys):
            raise ArtifactInputError("external_keys must not repeat")
        if not isinstance(self.parts, tuple) or not all(
            isinstance(item, ArtifactPart) for item in self.parts
        ):
            raise ArtifactInputError("parts must be a tuple of ArtifactPart")
        _require_optional_text(self.title, "title")
        _require_optional_url(self.url)
        if self.diagnostic is not None:
            _require_token(self.diagnostic, "diagnostic")
