"""Shared helpers for project_profile pack tests."""

from __future__ import annotations

from pathlib import Path

from test.fixtures.project_intelligence.loader import FIXTURE_ROOT, fixture_path

from packs.software_delivery.project_profile.intake import ProfileEvidence, ingest_profile_evidence


def load_component_files(relative_root: str) -> list[dict[str, str]]:
    """Load text files under a fixture subtree as path/content pairs."""
    root = fixture_path(relative_root)
    files: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        # Keep IDE/type scaffolding out of profile evidence payloads.
        if path.name in {"tsconfig.json", "jsconfig.json"} or path.name.endswith(
            ".d.ts"
        ):
            continue
        rel = path.relative_to(root).as_posix()
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files.append({"path": rel, "content": content})
    return files


def evidence_for_components(mapping: dict[str, str]) -> ProfileEvidence:
    """Build ProfileEvidence from component label → fixture subdirectory."""
    groups = [
        {"component": label, "files": load_component_files(relative)}
        for label, relative in mapping.items()
    ]
    return ingest_profile_evidence(groups)


def a0_evidence() -> ProfileEvidence:
    """Client-supplied evidence for the Part A0 multi-component fixture."""
    return evidence_for_components(
        {
            "proj-orders": "acme/proj-orders",
            "proj-tests": "acme/proj-tests",
            "proj-e2e": "acme/proj-e2e",
            "proj-web": "acme/proj-web",
        }
    )


def variant_evidence(name: str) -> ProfileEvidence:
    """Load a profile_variants/<name> tree as one implicit component."""
    return ingest_profile_evidence(
        [{"files": load_component_files(f"profile_variants/{name}")}]
    )


assert FIXTURE_ROOT.is_dir()
assert isinstance(Path(), Path)
