"""Playwright reusable-component extraction — content-backed kinds (#429)."""

from __future__ import annotations

import re

from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import LineRange, ReusableComponent

_SCRIPT_SUFFIXES = (".ts", ".js", ".mjs", ".cjs")
_PLAYWRIGHT_IMPORT = re.compile(
    r"""from\s+['"]@playwright/test['"]|require\(\s*['"]@playwright/test['"]\s*\)"""
)
_TEST_CALL = re.compile(r"\btest\s*(?:\.describe)?\s*\(")
_EXPECT = re.compile(r"\bexpect\s*\(")
_PAGE_CLASS = re.compile(
    r"class\s+(\w+)\s*\{[^}]*\b(?:page|locator|goto|getByRole)\b",
    re.DOTALL | re.IGNORECASE,
)
_PAGE_TYPE = re.compile(r"\bPage\b")
_HELPER_EXPORT = re.compile(r"\bexport\s+(?:async\s+)?function\s+(\w+)")
_FIXTURE_EXTEND = re.compile(r"\b(?:test|base)\.extend\s*\(")
_HOOK = re.compile(
    r"\btest\.(?:beforeEach|afterEach|beforeAll|afterAll)\s*\("
)


class PlaywrightSpecExtractor:
    """Extract Playwright reusable kinds only when static content justifies them."""

    framework_id = "playwright"

    def extract(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> tuple[tuple[ReusableComponent, ...], tuple[str, ...]]:
        found: list[ReusableComponent] = []
        diagnostics: list[str] = []
        for file in files:
            if not _is_candidate_script(file.path):
                continue
            kind, signature = _classify(file)
            if kind is None:
                if _looks_like_spec_path(file.path):
                    diagnostics.append(
                        f"insufficient static evidence for playwright reusable "
                        f"component at {file.path}"
                    )
                continue
            lines = file.content.splitlines()
            end = len(lines) if lines else 1
            found.append(
                ReusableComponent(
                    component_id=f"{kind}:{file.path}",
                    kind=kind,
                    framework_id="playwright",
                    signature=signature,
                    path=file.path,
                    content_hash=file.content_hash,
                    line_range=LineRange(1, end),
                    documentation="",
                )
            )
        return tuple(found), tuple(diagnostics)


def _is_candidate_script(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return name.endswith(_SCRIPT_SUFFIXES)


def _looks_like_spec_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    if stem.endswith(".spec") or stem.endswith(".test"):
        return True
    return path.startswith("e2e/") or "/pages/" in f"/{path}" or path.startswith("pages/")


def _classify(file: EvidenceFile) -> tuple[str | None, str]:
    content = file.content
    basename = file.path.rsplit("/", 1)[-1]
    if _HOOK.search(content) and _PLAYWRIGHT_IMPORT.search(content):
        return "hook", basename
    if _FIXTURE_EXTEND.search(content) and _PLAYWRIGHT_IMPORT.search(content):
        return "fixture", basename
    page_match = _PAGE_CLASS.search(content)
    if page_match and (_PLAYWRIGHT_IMPORT.search(content) or _PAGE_TYPE.search(content)):
        return "page_object", page_match.group(1)
    if (
        _HELPER_EXPORT.search(content)
        and (_PLAYWRIGHT_IMPORT.search(content) or _PAGE_TYPE.search(content))
        and not _TEST_CALL.search(content)
    ):
        match = _HELPER_EXPORT.search(content)
        assert match is not None
        return "helper", match.group(1)
    if _PLAYWRIGHT_IMPORT.search(content) and (
        _TEST_CALL.search(content) or _EXPECT.search(content)
    ):
        return "test_spec", basename
    return None, ""
