"""Bounded OpenAPI / Swagger operation extraction (no remote $ref)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import yaml

from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactPart
from domain.knowledge import SourceDocument

_DEFAULT_MAX_BYTES = 1_048_576
_MAX_SUMMARY_LENGTH = 512
_SUPPORTED_OPENAPI = frozenset({"3.0.0", "3.0.1", "3.0.2", "3.0.3", "3.1.0"})
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


def _safe_summary(raw: object) -> str | None:
    """Collapse free-form OpenAPI summaries into ArtifactPart-safe text.

    OpenAPI allows multi-line YAML literals and arbitrary length; descriptor
    contracts reject control characters and text over 512 characters. Invalid
    summaries are dropped so the operation part still indexes.
    """
    if not isinstance(raw, str):
        return None
    cleaned = " ".join(raw.split())
    if not cleaned:
        return None
    if len(cleaned) > _MAX_SUMMARY_LENGTH:
        cleaned = cleaned[:_MAX_SUMMARY_LENGTH].rstrip()
    if not cleaned or any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        return None
    return cleaned


@dataclass(frozen=True, slots=True)
class OpenApiExtraction:
    kind: str
    parts: tuple[ArtifactPart, ...]
    external_keys: tuple[str, ...]
    diagnostic: str | None
    valid_spec_root: bool


def _unsupported() -> OpenApiExtraction:
    return OpenApiExtraction(
        kind=ArtifactKind.API_SPEC,
        parts=(),
        external_keys=(),
        diagnostic="unsupported",
        valid_spec_root=False,
    )


def _version_supported(payload: Mapping[str, object]) -> bool:
    openapi = payload.get("openapi")
    if isinstance(openapi, str):
        return openapi in _SUPPORTED_OPENAPI or openapi.startswith("3.0.") or openapi.startswith(
            "3.1."
        )
    swagger = payload.get("swagger")
    return swagger == "2.0"


def extract_openapi_parts(
    document: SourceDocument,
    *,
    max_bytes: int = _DEFAULT_MAX_BYTES,
) -> OpenApiExtraction:
    """Parse a local OpenAPI/Swagger document into operation parts and keys."""
    content = document.content
    if len(content.encode("utf-8")) > max_bytes:
        return _unsupported()
    try:
        payload = yaml.safe_load(content)
    except Exception:
        return _unsupported()
    if not isinstance(payload, Mapping):
        return _unsupported()
    if not _version_supported(payload):
        return _unsupported()
    paths = payload.get("paths")
    if not isinstance(paths, Mapping):
        return OpenApiExtraction(
            kind=ArtifactKind.API_SPEC,
            parts=(),
            external_keys=(),
            diagnostic=None,
            valid_spec_root=True,
        )
    parts: list[ArtifactPart] = []
    keys: list[str] = []
    for path, item in paths.items():
        if not isinstance(path, str) or not isinstance(item, Mapping):
            continue
        for method, operation in item.items():
            if not isinstance(method, str) or method.lower() not in _HTTP_METHODS:
                continue
            if not isinstance(operation, Mapping):
                continue
            method_upper = method.upper()
            part_key = f"{method_upper} {path}"
            operation_id = operation.get("operationId")
            op_id = (
                operation_id.strip()
                if isinstance(operation_id, str) and operation_id.strip()
                else None
            )
            summary = _safe_summary(operation.get("summary"))
            responses = operation.get("responses")
            codes: list[str] = []
            if isinstance(responses, Mapping):
                codes = [str(code) for code in responses.keys()]
            parts.append(
                ArtifactPart(
                    kind=ArtifactKind.API_OPERATION,
                    part_key=part_key,
                    operation_id=op_id,
                    summary=summary,
                    response_codes=tuple(codes),
                )
            )
            keys.append(part_key)
            if op_id is not None:
                keys.append(op_id)
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    ordered_keys: list[str] = []
    for key in keys:
        if key not in seen:
            seen.add(key)
            ordered_keys.append(key)
    return OpenApiExtraction(
        kind=ArtifactKind.API_SPEC,
        parts=tuple(parts),
        external_keys=tuple(ordered_keys),
        diagnostic=None,
        valid_spec_root=True,
    )
