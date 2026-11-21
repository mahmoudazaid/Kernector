"""Selenium page-object / helper extraction — content-backed (#429)."""

from __future__ import annotations

import re

from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import LineRange, ReusableComponent

_SELENIUM_IMPORT = re.compile(
    r"from\s+selenium\b|import\s+selenium\b|org\.openqa\.selenium|"
    r"require\(\s*['\"]selenium-webdriver['\"]\s*\)|"
    r"from\s+['\"]selenium-webdriver['\"]"
)
_PAGE_CLASS = re.compile(
    r"class\s+(\w*(?:Page|PageObject)\w*)\b",
)
_FIND = re.compile(
    r"\b(?:find_element|findElement|By\.|driver\.)\b"
)
_HELPER_FN = re.compile(
    r"(?:def|function|public\s+\w+)\s+(\w+)\s*\("
)


class SeleniumPageExtractor:
    framework_id = "selenium"

    def extract(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> tuple[tuple[ReusableComponent, ...], tuple[str, ...]]:
        found: list[ReusableComponent] = []
        diagnostics: list[str] = []
        for file in files:
            lower_path = file.path.lower()
            candidate = (
                "/pages/" in f"/{lower_path}"
                or "/pageobjects/" in f"/{lower_path}"
                or "/page_objects/" in f"/{lower_path}"
                or lower_path.endswith("page.py")
                or "pageobject" in lower_path.replace("_", "").replace("-", "")
            )
            if not candidate:
                continue
            has_import = _SELENIUM_IMPORT.search(file.content) is not None
            has_find = _FIND.search(file.content) is not None
            # Only diagnose when the file shows Selenium usage; avoid flagging
            # unrelated pages/ trees (e.g. Next.js) that merely match the path.
            if not has_import or not has_find:
                if has_import:
                    diagnostics.append(
                        f"insufficient static evidence for selenium reusable "
                        f"component at {file.path}"
                    )
                continue
            lines = file.content.splitlines()
            end = len(lines) if lines else 1
            page = _PAGE_CLASS.search(file.content)
            if page:
                kind = "page_object"
                signature = page.group(1)
            else:
                helper = _HELPER_FN.search(file.content)
                if not helper:
                    diagnostics.append(
                        f"insufficient static evidence for selenium reusable "
                        f"component at {file.path}"
                    )
                    continue
                kind = "helper"
                signature = helper.group(1)
            found.append(
                ReusableComponent(
                    component_id=f"{kind}:{file.path}",
                    kind=kind,
                    framework_id="selenium",
                    signature=signature,
                    path=file.path,
                    content_hash=file.content_hash,
                    line_range=LineRange(1, end),
                    documentation="",
                )
            )
        return tuple(found), tuple(diagnostics)
