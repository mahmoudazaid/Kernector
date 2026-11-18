"""Next.js / React path-convention extractor — no TypeScript parsing."""

from __future__ import annotations

from packs.software_delivery.project_profile.intake import EvidenceFile
from packs.software_delivery.project_profile.models import LineRange, ReusableComponent

_SCRIPT_SUFFIXES = (".tsx", ".ts", ".jsx", ".js")


class FrontendPathExtractor:
    """Extract routes, UI components, and API clients from path conventions."""

    framework_id = "react"

    def extract(
        self, component_label: str, files: tuple[EvidenceFile, ...]
    ) -> tuple[tuple[ReusableComponent, ...], tuple[str, ...]]:
        found: list[ReusableComponent] = []
        for file in files:
            kind = _frontend_kind(file.path)
            if kind is None:
                continue
            lines = file.content.splitlines()
            end = len(lines) if lines else 1
            found.append(
                ReusableComponent(
                    component_id=f"{kind}:{file.path}",
                    kind=kind,
                    framework_id="next" if kind == "route" else "react",
                    signature=file.path.rsplit("/", 1)[-1],
                    path=file.path,
                    content_hash=file.content_hash,
                    line_range=LineRange(1, end),
                    documentation="",
                )
            )
        return tuple(found), ()


def _frontend_kind(path: str) -> str | None:
    name = path.rsplit("/", 1)[-1]
    if _is_under(path, "app/") and _basename_is(name, "page", _SCRIPT_SUFFIXES):
        return "route"
    if _is_under(path, "components/") and path.endswith(_SCRIPT_SUFFIXES):
        return "ui_component"
    if _is_under(path, "lib/api/") and path.endswith(_SCRIPT_SUFFIXES):
        return "api_client"
    return None


def _is_under(path: str, prefix: str) -> bool:
    return path.startswith(prefix) or f"/{prefix}" in f"/{path}"


def _basename_is(name: str, stem: str, suffixes: tuple[str, ...]) -> bool:
    return any(name == f"{stem}{suffix}" for suffix in suffixes)
