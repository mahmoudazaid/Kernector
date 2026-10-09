"""Provider-neutral path-prefix rules for project components (#372)."""

from __future__ import annotations

import pytest

from domain.project.errors import ProjectInputError
from domain.project.paths import (
    is_valid_path,
    normalize_path_prefix,
    prefix_depth,
    prefix_matches,
)


@pytest.mark.parametrize(
    "raw,canonical",
    [
        ("", ""),
        ("web", "web"),
        ("web/", "web"),
        ("services/orders", "services/orders"),
        ("services/orders/", "services/orders"),
        ("Web", "Web"),
        ("docs/openapi.yaml", "docs/openapi.yaml"),
    ],
)
def test_prefix_is_normalized(raw: str, canonical: str) -> None:
    assert normalize_path_prefix(raw) == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "/web",
        "web//",
        "a//b",
        "./web",
        "web/..",
        "a/./b",
        "web\\app",
        "web\x00",
        "web\napp",
        "/",
        "x" * 1025,
    ],
)
def test_invalid_prefix_is_rejected(raw: str) -> None:
    with pytest.raises(ProjectInputError):
        normalize_path_prefix(raw)


def test_non_string_prefix_is_rejected() -> None:
    with pytest.raises(ProjectInputError):
        normalize_path_prefix(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "path,valid",
    [
        ("web/app.tsx", True),
        ("README.md", True),
        ("orders/cancel:v2.py", True),
        ("", False),
        ("web/", False),
        ("/web/app.tsx", False),
        ("web/../x", False),
        ("web\\x", False),
    ],
)
def test_document_path_validity(path: str, valid: bool) -> None:
    assert is_valid_path(path) is valid


@pytest.mark.parametrize(
    "prefix,path,matches",
    [
        ("web", "web/app.tsx", True),
        ("web", "web", True),
        ("web", "website/app.tsx", False),
        ("web", "webapp", False),
        ("services/orders", "services/orders/cancel.py", True),
        ("services/orders", "services/orders-v2/cancel.py", False),
        ("", "anything/at/all.py", True),
        ("web", "Web/app.tsx", False),
    ],
)
def test_prefix_matches_on_directory_boundaries(
    prefix: str, path: str, matches: bool
) -> None:
    assert prefix_matches(prefix, path) is matches


def test_prefix_depth_counts_segments() -> None:
    assert prefix_depth("") == 0
    assert prefix_depth("web") == 1
    assert prefix_depth("services/orders") == 2
