"""Cypress support/fixture extraction — content-backed (#429)."""

from __future__ import annotations

import re

from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import LineRange, ReusableComponent

_COMMAND_ADD = re.compile(
    r"""Cypress\.Commands\.add\(\s*['"](\w+)['"]""",
)
_FIXTURE_JSON_KEYS = re.compile(r'''"(\w+)"\s*:''')


class CypressSupportExtractor:
    framework_id = "cypress"

    def extract(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> tuple[tuple[ReusableComponent, ...], tuple[str, ...]]:
        found: list[ReusableComponent] = []
        diagnostics: list[str] = []
        for file in files:
            if file.path.startswith("cypress/support/") and file.path.endswith(
                (".ts", ".js", ".mjs", ".cjs")
            ):
                commands = list(_COMMAND_ADD.finditer(file.content))
                if not commands:
                    diagnostics.append(
                        f"insufficient static evidence for cypress helpers at {file.path}"
                    )
                    continue
                lines = file.content.splitlines()
                end = len(lines) if lines else 1
                for match in commands:
                    start = file.content[: match.start()].count("\n") + 1
                    found.append(
                        ReusableComponent(
                            component_id=f"helper:{file.path}:{match.group(1)}",
                            kind="helper",
                            framework_id="cypress",
                            signature=match.group(1),
                            path=file.path,
                            content_hash=file.content_hash,
                            line_range=LineRange(start, end),
                            documentation="",
                        )
                    )
            elif file.path.startswith("cypress/fixtures/") and file.path.endswith(
                (".json", ".js", ".ts")
            ):
                if not file.content.strip() or (
                    file.path.endswith(".json")
                    and not _FIXTURE_JSON_KEYS.search(file.content)
                ):
                    diagnostics.append(
                        f"insufficient static evidence for cypress fixture at {file.path}"
                    )
                    continue
                lines = file.content.splitlines()
                end = len(lines) if lines else 1
                found.append(
                    ReusableComponent(
                        component_id=f"fixture:{file.path}",
                        kind="fixture",
                        framework_id="cypress",
                        signature=file.path.rsplit("/", 1)[-1],
                        path=file.path,
                        content_hash=file.content_hash,
                        line_range=LineRange(1, end),
                        documentation="",
                    )
                )
        return tuple(found), tuple(diagnostics)
