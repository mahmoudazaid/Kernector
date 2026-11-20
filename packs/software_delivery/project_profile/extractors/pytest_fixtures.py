"""Pytest conftest fixture extraction — content-backed only (#429)."""

from __future__ import annotations

import re

from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import LineRange, ReusableComponent

_FIXTURE_DEF = re.compile(
    r"""@(?:pytest\.)?fixture\b[^\n]*\n(?:async\s+)?def\s+(\w+)\s*\(""",
    re.MULTILINE,
)


class PytestFixtureExtractor:
    """Extract pytest fixtures only when ``@pytest.fixture`` (or alias) is present."""

    framework_id = "pytest"

    def extract(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> tuple[tuple[ReusableComponent, ...], tuple[str, ...]]:
        found: list[ReusableComponent] = []
        diagnostics: list[str] = []
        for file in files:
            name = file.path.rsplit("/", 1)[-1]
            if name != "conftest.py" and not file.path.endswith("/conftest.py"):
                continue
            matches = list(_FIXTURE_DEF.finditer(file.content))
            if not matches:
                if file.content.strip():
                    diagnostics.append(
                        f"insufficient static evidence for pytest fixtures at {file.path}"
                    )
                continue
            lines = file.content.splitlines()
            for match in matches:
                start_line = file.content[: match.start()].count("\n") + 1
                # Approximate end as next def or EOF.
                rest = file.content[match.end() :]
                next_def = re.search(r"\n(?:async\s+)?def\s+", rest)
                if next_def:
                    end_line = start_line + rest[: next_def.start()].count("\n")
                else:
                    end_line = len(lines) if lines else start_line
                if end_line < start_line:
                    end_line = start_line
                signature = match.group(1)
                found.append(
                    ReusableComponent(
                        component_id=f"fixture:{file.path}:{signature}",
                        kind="fixture",
                        framework_id="pytest",
                        signature=signature,
                        path=file.path,
                        content_hash=file.content_hash,
                        line_range=LineRange(start_line, end_line),
                        documentation="",
                    )
                )
        return tuple(found), tuple(diagnostics)
