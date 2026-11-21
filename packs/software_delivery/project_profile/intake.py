"""Client-supplied profile evidence intake (#387 Phase A)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from domain.project.paths import is_valid_path
from packs.software_delivery.project_profile.errors import ProjectProfileValidationError
from packs.software_delivery.project_profile.limits import (
    MAX_PROFILE_COMPONENTS,
    MAX_PROFILE_DIAGNOSTICS,
    MAX_PROFILE_FILE_BYTES,
    MAX_PROFILE_FILES,
    MAX_PROFILE_LINE_CHARS,
    MAX_PROFILE_PATH_CHARS,
    MAX_PROFILE_TOTAL_BYTES,
)
from packs.software_delivery.project_profile.models import IMPLICIT_COMPONENT

_EXCLUDED_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
    }
)
_EXCLUDED_SUFFIXES = (".pem", ".key", ".p12", ".pfx", ".jks", ".keystore")
_EXCLUDED_SEGMENTS = frozenset(
    {
        "node_modules",
        "vendor",
        ".git",
        "dist",
        "build",
        ".next",
        "__pycache__",
        ".venv",
        "venv",
    }
)
# Fail-closed secret scan: keep real assignments/tokens, skip Robot/docs
# placeholders such as ``password=${password}`` and prose ``Bearer auth``.
_SECRET_CONTENT = re.compile(
    r"(?i)("
    # Lookbehind skips ${…} / $VAR templates only — not word chars, so
    # prefixed names like DB_PASSWORD= and AWS_SECRET_ACCESS_KEY= still match.
    r"(?<![${])(?:API[_-]?KEY|SECRET[_-]?[A-Z0-9_]*|PASSWORD)\s*=\s*"
    r"(?!\$\{|\$[A-Za-z_]|{{)\S+"
    r"|Bearer\s+[A-Za-z0-9\-._~+/]{16,}={0,2}"
    r"|-----BEGIN (?:RSA )?PRIVATE KEY-----"
    r")"
)


@dataclass(frozen=True, slots=True)
class EvidenceFile:
    """One kept client-supplied evidence file."""

    path: str
    content: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class EvidenceComponent:
    """Evidence files for one client-declared or implicit component."""

    label: str
    files: tuple[EvidenceFile, ...]


@dataclass(frozen=True, slots=True)
class ProfileEvidence:
    """Normalized, filtered, untrusted client-supplied evidence."""

    components: tuple[EvidenceComponent, ...]
    diagnostics: tuple[str, ...]
    evidence_origin: str = "client_supplied"
    untrusted_evidence: bool = True


def content_hash(content: str) -> str:
    """Return the SHA-256 hex digest of UTF-8 ``content``."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def ingest_profile_evidence(groups: object) -> ProfileEvidence:
    """Normalize and filter client-supplied evidence groups.

    Each group is ``{"component"?: str, "files": [{"path", "content"}, ...]}``.
    Unsafe paths and oversize input raise. Secret/excluded files are dropped
    with sanitized diagnostics.
    """
    if not isinstance(groups, Sequence) or isinstance(groups, (str, bytes)):
        raise ProjectProfileValidationError("evidence must be a non-empty list")
    if not groups:
        raise ProjectProfileValidationError("evidence must be a non-empty list")
    if len(groups) > MAX_PROFILE_COMPONENTS:
        raise ProjectProfileValidationError(
            f"at most {MAX_PROFILE_COMPONENTS} evidence groups are allowed"
        )

    components: list[EvidenceComponent] = []
    diagnostics: list[str] = []
    total_bytes = 0
    total_files = 0
    seen_labels: set[str] = set()

    for group in groups:
        component, group_diags, group_bytes, group_files = _ingest_group(group)
        if component.label in seen_labels:
            raise ProjectProfileValidationError(
                "duplicate component label is not allowed"
            )
        seen_labels.add(component.label)
        total_files += group_files
        if total_files > MAX_PROFILE_FILES:
            raise ProjectProfileValidationError(
                f"at most {MAX_PROFILE_FILES} files are allowed"
            )
        total_bytes += group_bytes
        if total_bytes > MAX_PROFILE_TOTAL_BYTES:
            raise ProjectProfileValidationError(
                f"total evidence must be at most {MAX_PROFILE_TOTAL_BYTES} bytes"
            )
        components.append(component)
        diagnostics.extend(group_diags)

    return ProfileEvidence(
        components=tuple(components),
        diagnostics=tuple(diagnostics[:MAX_PROFILE_DIAGNOSTICS]),
    )


def _ingest_group(
    group: object,
) -> tuple[EvidenceComponent, list[str], int, int]:
    if not isinstance(group, Mapping):
        raise ProjectProfileValidationError("each evidence group must be an object")
    unexpected = set(group) - {"component", "files"}
    if unexpected:
        fields = ", ".join(sorted(map(str, unexpected)))
        raise ProjectProfileValidationError(
            f"evidence group has unsupported fields: {fields}"
        )
    label = group.get("component", IMPLICIT_COMPONENT)
    if label is None:
        label = IMPLICIT_COMPONENT
    if not isinstance(label, str):
        raise ProjectProfileValidationError("component must be a string when provided")
    if "\0" in label or any(ord(c) < 32 for c in label):
        raise ProjectProfileValidationError("component label is invalid")

    files_raw = group.get("files")
    if not isinstance(files_raw, Sequence) or isinstance(files_raw, (str, bytes)):
        raise ProjectProfileValidationError("files must be a non-empty list")
    if not files_raw:
        raise ProjectProfileValidationError("files must be a non-empty list")

    kept: list[EvidenceFile] = []
    diagnostics: list[str] = []
    seen: set[str] = set()
    group_bytes = 0
    considered = 0

    for item in files_raw:
        path, content = _file_item(item)
        considered += 1
        if path in seen:
            raise ProjectProfileValidationError(
                f"duplicate path within component: {path}"
            )
        seen.add(path)

        size = len(content.encode("utf-8"))
        if size > MAX_PROFILE_FILE_BYTES:
            raise ProjectProfileValidationError(
                f"file exceeds size limit ({MAX_PROFILE_FILE_BYTES} bytes): {path}"
            )
        if _is_excluded_path(path):
            diagnostics.append(f"excluded path dropped: {path}")
            continue
        if "\0" in content:
            diagnostics.append(f"binary or null-byte content dropped: {path}")
            continue
        if any(len(line) > MAX_PROFILE_LINE_CHARS for line in content.splitlines()):
            diagnostics.append(f"pathological line length dropped: {path}")
            continue
        if _SECRET_CONTENT.search(content):
            diagnostics.append(f"secret-bearing content dropped: {path}")
            continue

        group_bytes += size
        kept.append(
            EvidenceFile(path=path, content=content, content_hash=content_hash(content))
        )

    return (
        EvidenceComponent(label=label, files=tuple(kept)),
        diagnostics,
        group_bytes,
        considered,
    )


def _file_item(item: object) -> tuple[str, str]:
    if not isinstance(item, Mapping) or set(item) != {"path", "content"}:
        raise ProjectProfileValidationError("each file must have only path and content")
    path, content = item["path"], item["content"]
    if not isinstance(path, str) or not path.strip():
        raise ProjectProfileValidationError("path must be a non-empty string")
    if len(path) > MAX_PROFILE_PATH_CHARS:
        raise ProjectProfileValidationError(
            f"path must be at most {MAX_PROFILE_PATH_CHARS} characters"
        )
    if path.startswith("~") or path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ProjectProfileValidationError(f"unsafe path rejected: {path}")
    if "\\" in path or ".." in path.split("/"):
        raise ProjectProfileValidationError(f"unsafe path rejected: {path}")
    normalized = path.strip().removesuffix("/")
    if not is_valid_path(normalized):
        raise ProjectProfileValidationError(f"unsafe path rejected: {path}")
    if not isinstance(content, str):
        raise ProjectProfileValidationError("content must be text")
    return normalized, content


def _is_excluded_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    if name in _EXCLUDED_NAMES or name.startswith(".env"):
        return True
    if any(name.endswith(suffix) for suffix in _EXCLUDED_SUFFIXES):
        return True
    segments = path.split("/")
    return any(segment in _EXCLUDED_SEGMENTS for segment in segments)
