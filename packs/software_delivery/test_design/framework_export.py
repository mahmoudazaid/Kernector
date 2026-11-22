"""Package framework artifacts into the #359 safe file contract (#368)."""

from __future__ import annotations

from packs.software_delivery.test_design.framework_contracts import (
    FrameworkArtifactResult,
    FrameworkFile,
)


def package_framework_files(
    result: FrameworkArtifactResult,
) -> tuple[FrameworkFile, ...]:
    """Return #359 file tuples from a successful generation result.

    Non-ok statuses yield no files. Paths are already validated on
    ``FrameworkFile`` construction (relative, no ``..`` segments).
    """
    if result.status != "ok":
        return ()
    return tuple(
        FrameworkFile(
            filename=item.filename,
            suggested_path=_normalize_suggested_path(item.suggested_path),
            content=item.content if item.content.endswith("\n") else item.content + "\n",
        )
        for item in result.files
    )


def _normalize_suggested_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip().lstrip("/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized
