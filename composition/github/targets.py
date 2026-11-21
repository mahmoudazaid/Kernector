"""Normalize and validate GitHub multi-repo selection targets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from application.errors import InputRejectedError
from composition.github.models import GitHubRepoTarget

_UNSAFE_OWNER_REPO_CHARS = frozenset("/\\")


def target_to_payload(target: GitHubRepoTarget) -> dict[str, object]:
    """Serialize a target for opaque grant persistence."""
    payload: dict[str, object] = {
        "owner": target.owner,
        "repo": target.repo,
        "ref": target.ref,
        "include_prefixes": list(target.include_prefixes),
        "exclude_prefixes": list(target.exclude_prefixes),
    }
    if target.extensions is None:
        payload["extensions"] = None
    else:
        payload["extensions"] = list(target.extensions)
    if target.filename_globs is None:
        payload["filename_globs"] = None
    else:
        payload["filename_globs"] = list(target.filename_globs)
    return payload


def target_from_payload(raw: Mapping[str, object]) -> GitHubRepoTarget:
    """Rebuild a target from persisted JSON (no re-validation)."""
    owner = raw.get("owner")
    repo = raw.get("repo")
    if not isinstance(owner, str) or not isinstance(repo, str):
        raise InputRejectedError("Each repository target needs an owner and name.")
    raw_ref = raw.get("ref")
    if isinstance(raw_ref, str) and raw_ref.strip():
        ref: str | None = raw_ref.strip()
    else:
        ref = None
    return GitHubRepoTarget(
        owner=owner,
        repo=repo,
        ref=ref,
        include_prefixes=_tuple_of_str(raw.get("include_prefixes")),
        exclude_prefixes=_tuple_of_str(raw.get("exclude_prefixes")),
        extensions=_optional_str_tuple(raw.get("extensions"), present="extensions" in raw),
        filename_globs=_optional_str_tuple(
            raw.get("filename_globs"), present="filename_globs" in raw
        ),
    )


def repositories_from_connection(
    *,
    owner: str | None,
    repo: str | None,
    repositories: Sequence[Mapping[str, object]],
) -> tuple[GitHubRepoTarget, ...]:
    """Load targets from grant rows, migrating legacy flat owner/repo."""
    if repositories:
        return tuple(target_from_payload(row) for row in repositories)
    if owner and repo:
        return (GitHubRepoTarget(owner=owner, repo=repo),)
    return ()


def normalize_and_validate_targets(
    repositories: Sequence[GitHubRepoTarget] | None,
    *,
    owner: str | None,
    repo: str | None,
    max_repositories: int,
) -> tuple[GitHubRepoTarget, ...]:
    """Build the ordered target list from multi-repo or legacy flat input."""
    if repositories is not None:
        raw_targets = tuple(repositories)
    elif owner is not None or repo is not None:
        if (owner is None) != (repo is None):
            raise InputRejectedError(
                "Repository owner and name must be set together."
            )
        assert owner is not None and repo is not None
        raw_targets = (GitHubRepoTarget(owner=owner, repo=repo),)
    else:
        raw_targets = ()

    if len(raw_targets) > max_repositories:
        raise InputRejectedError(
            f"At most {max_repositories} repositories can be selected."
        )

    normalized: list[GitHubRepoTarget] = []
    seen: set[str] = set()
    for target in raw_targets:
        clean = _normalize_target(target)
        key = clean.identity.key()
        if key in seen:
            raise InputRejectedError(
                "Duplicate repository identities are not allowed."
            )
        seen.add(key)
        normalized.append(clean)
    return tuple(normalized)


def _normalize_target(target: GitHubRepoTarget) -> GitHubRepoTarget:
    owner = _require_owner_repo_component(target.owner, "owner")
    repo = _require_owner_repo_component(target.repo, "repo")
    if target.ref is None:
        ref: str | None = None
    elif isinstance(target.ref, str) and target.ref.strip():
        ref = target.ref.strip()
    else:
        ref = None
    return GitHubRepoTarget(
        owner=owner,
        repo=repo,
        ref=ref,
        include_prefixes=_normalize_prefixes(target.include_prefixes),
        exclude_prefixes=_normalize_prefixes(target.exclude_prefixes),
        extensions=_normalize_extensions(target.extensions),
        filename_globs=_normalize_globs(target.filename_globs),
    )


def _require_owner_repo_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputRejectedError(
            f"Repository {label} must be a non-empty string."
        )
    cleaned = value.strip()
    if any(ch in cleaned for ch in _UNSAFE_OWNER_REPO_CHARS) or ".." in cleaned:
        raise InputRejectedError(
            f"Repository {label} contains unsafe path characters."
        )
    if cleaned.startswith(".") or "\x00" in cleaned:
        raise InputRejectedError(
            f"Repository {label} contains unsafe path characters."
        )
    return cleaned


def _normalize_prefixes(prefixes: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    for raw in prefixes:
        if not isinstance(raw, str):
            raise InputRejectedError("Path prefixes must be strings.")
        cleaned = raw.strip().replace("\\", "/")
        if not cleaned:
            raise InputRejectedError("Path prefixes must not be empty.")
        if cleaned.startswith("/") or cleaned.startswith("~"):
            raise InputRejectedError("Path prefixes must be relative.")
        parts = [part for part in cleaned.split("/") if part != ""]
        if not parts or any(part == ".." for part in parts):
            raise InputRejectedError(
                "Path prefixes must not contain traversal segments."
            )
        if any("\x00" in part for part in parts):
            raise InputRejectedError("Path prefixes contain unsafe characters.")
        normalized = "/".join(parts) + "/"
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _normalize_extensions(
    extensions: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    if extensions is None:
        return None
    result: list[str] = []
    for raw in extensions:
        if not isinstance(raw, str):
            raise InputRejectedError("File extensions must be strings.")
        cleaned = raw.strip().lower()
        if not cleaned:
            continue
        if not cleaned.startswith("."):
            cleaned = f".{cleaned}"
        if cleaned not in result:
            result.append(cleaned)
    return tuple(result)


def _normalize_globs(
    globs: tuple[str, ...] | None,
) -> tuple[str, ...] | None:
    if globs is None:
        return None
    result: list[str] = []
    for raw in globs:
        if not isinstance(raw, str):
            raise InputRejectedError("Filename globs must be strings.")
        cleaned = raw.strip()
        if not cleaned:
            continue
        if cleaned not in result:
            result.append(cleaned)
    return tuple(result)


def _tuple_of_str(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _optional_str_tuple(
    value: object, *, present: bool
) -> tuple[str, ...] | None:
    if not present or value is None:
        return None
    if not isinstance(value, list):
        return None
    return tuple(item for item in value if isinstance(item, str))


def resolve_target_file_rules(
    target: GitHubRepoTarget,
    *,
    workspace_extensions: Sequence[str],
) -> tuple[frozenset[str], tuple[str, ...]]:
    """Resolve extensions/globs for listing.

    ``None`` inherits workspace extensions / empty globs. Explicit ``()``
    does not fall back.
    """
    if target.extensions is None:
        extensions = frozenset(workspace_extensions)
    else:
        extensions = frozenset(target.extensions)
    globs = () if target.filename_globs is None else tuple(target.filename_globs)
    return extensions, globs
