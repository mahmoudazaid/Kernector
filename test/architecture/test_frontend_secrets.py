"""The Hub never reads server-only connector secrets or exposes them as public env."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = REPO_ROOT / "web"
_SKIPPED_DIRS = {"node_modules", ".next", "coverage", "out", "dist"}
_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".md"}
_FORBIDDEN = re.compile(r"JIRA_DC_TOKEN|NEXT_PUBLIC_JIRA\w*")


def _web_files() -> list[Path]:
    files: list[Path] = []
    for path in WEB_ROOT.rglob("*"):
        if any(part in _SKIPPED_DIRS for part in path.relative_to(WEB_ROOT).parts):
            continue
        if path.is_file() and (
            path.suffix in _SOURCE_SUFFIXES or path.name.startswith(".env")
        ):
            files.append(path)
    return files


def test_web_sources_never_reference_the_jira_data_center_token() -> None:
    files = _web_files()
    offenders = [
        f"{path.relative_to(REPO_ROOT)}: {match.group(0)}"
        for path in files
        for match in _FORBIDDEN.finditer(path.read_text(encoding="utf-8", errors="ignore"))
    ]

    assert files, "web/ sources were not found"
    assert offenders == []
