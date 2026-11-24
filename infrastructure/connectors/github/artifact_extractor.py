"""GitHub repo files and issues → ArtifactDescriptor."""

from __future__ import annotations

from collections.abc import Sequence
from fnmatch import fnmatch
from pathlib import PurePosixPath

from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.knowledge import SourceDocument, SourceType
from infrastructure.artifact.openapi import extract_openapi_parts

DEFAULT_TEST_GLOBS: tuple[str, ...] = (
    "tests/**",
    "test/**",
    "e2e/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/*.robot",
    "**/*.spec.ts",
    "**/*.spec.js",
    "**/*_spec.rb",
)

DEFAULT_TEST_SUPPORT_GLOBS: tuple[str, ...] = (
    "**/resources/**",
    "**/*.resource",
    "**/fixtures/**",
    "**/conftest.py",
    "**/steps/**",
    "**/step_definitions/**",
)


def _path_matches(path: str, patterns: Sequence[str]) -> bool:
    posix = path.replace("\\", "/")
    name = PurePosixPath(posix).name
    return any(
        fnmatch(posix, pattern) or fnmatch(name, pattern) for pattern in patterns
    )


def _roles(extra: dict[str, str]) -> frozenset[str]:
    raw = extra.get("association_roles", "")
    if not raw.strip():
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


class GitHubArtifactDescriptorExtractor:
    """Classify GitHub files and issues into artifact descriptors."""

    def __init__(
        self,
        *,
        test_globs: Sequence[str] = DEFAULT_TEST_GLOBS,
        test_support_globs: Sequence[str] = DEFAULT_TEST_SUPPORT_GLOBS,
    ) -> None:
        self._test_globs = tuple(test_globs)
        self._test_support_globs = tuple(test_support_globs)

    def describe(self, document: SourceDocument) -> ArtifactDescriptor | None:
        if document.reference.source_type != SourceType.GITHUB:
            return None
        extra = dict(document.metadata.extra)
        if "github_issue_number" in extra:
            return self._describe_issue(document, extra)
        if "github_path" in extra:
            return self._describe_file(document, extra)
        return None

    def _describe_file(
        self, document: SourceDocument, extra: dict[str, str]
    ) -> ArtifactDescriptor | None:
        path = extra.get("github_path", "")
        revision = extra.get("github_blob_sha", "")
        if not path.strip() or not revision.strip():
            return None
        roles = _roles(extra)
        url = extra.get("github_url")
        name = PurePosixPath(path.replace("\\", "/")).name.lower()
        if name.startswith("openapi.") or name.startswith("swagger."):
            extraction = extract_openapi_parts(document)
            return ArtifactDescriptor(
                reference=document.reference,
                revision=revision,
                kind=extraction.kind,
                external_keys=extraction.external_keys,
                parts=extraction.parts,
                title=document.metadata.title,
                url=url if isinstance(url, str) and url.strip() else None,
                diagnostic=extraction.diagnostic,
            )
        if _path_matches(path, self._test_support_globs):
            kind = ArtifactKind.TEST_SUPPORT
        elif "testing" in roles or _path_matches(path, self._test_globs):
            kind = ArtifactKind.AUTOMATED_TEST
        else:
            kind = ArtifactKind.CODE_FILE
        return ArtifactDescriptor(
            reference=document.reference,
            revision=revision,
            kind=kind,
            external_keys=(),
            title=document.metadata.title,
            url=url if isinstance(url, str) and url.strip() else None,
        )

    def _describe_issue(
        self, document: SourceDocument, extra: dict[str, str]
    ) -> ArtifactDescriptor | None:
        number = extra.get("github_issue_number", "").strip()
        repository = extra.get("github_repository", "").strip()
        revision = extra.get("github_updated_at", "").strip()
        if not number or not repository or not revision:
            return None
        url = extra.get("github_issue_url")
        return ArtifactDescriptor(
            reference=document.reference,
            revision=revision,
            kind=ArtifactKind.WORK_ITEM,
            external_keys=(f"{repository}#{number}",),
            title=document.metadata.title,
            url=url if isinstance(url, str) and url.strip() else None,
        )
