"""Build bounded project key/API catalogues for deterministic matching (#375)."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Sequence

from domain.artifact.kinds import ArtifactKind
from domain.artifact.models import ArtifactDescriptor
from domain.artifact.ports import ArtifactIndex
from domain.knowledge import SourceReference
from domain.relationship.matching import (
    ApiOperationCatalogueEntry,
    MatchLimits,
    ProjectKeyCatalogue,
)
from domain.relationship.api_paths import normalize_method_path

ProjectIdsForSource = Callable[[SourceReference], tuple[str, ...]]

_KEY_PREFIX = re.compile(r"^([A-Z][A-Z0-9_]*)-[1-9][0-9]*$")


def derive_prefixes(keys: Sequence[str]) -> tuple[str, ...]:
    """Return sorted unique issue-key prefixes from ``PREFIX-n`` shaped keys."""
    prefixes: set[str] = set()
    for key in keys:
        match = _KEY_PREFIX.fullmatch(key)
        if match is not None:
            prefixes.add(match.group(1))
    return tuple(sorted(prefixes))


def catalogue_fingerprint(
    key_catalogue: ProjectKeyCatalogue,
    api_operations: Sequence[ApiOperationCatalogueEntry],
) -> str:
    """Stable hash of the project key/API catalogue used in watermarks."""
    lines = [
        "keys:" + ",".join(sorted(key_catalogue.keys)),
        "prefixes:" + ",".join(sorted(key_catalogue.prefixes)),
    ]
    for entry in sorted(
        api_operations,
        key=lambda item: (
            item.operation_id or "",
            item.method_path or "",
        ),
    ):
        lines.append(f"op:{entry.operation_id or ''}|{entry.method_path or ''}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def limits_fingerprint(limits: MatchLimits) -> str:
    return (
        f"{limits.max_content_bytes}:{limits.max_mentions}:"
        f"{limits.max_catalogue_entries}:{limits.max_compiled_pattern_size}"
    )


class ProjectCatalogueBuilder:
    """Enumerate known keys and current API operations for one project."""

    def __init__(
        self,
        index: ArtifactIndex,
        *,
        project_ids_for: ProjectIdsForSource,
        limits: MatchLimits,
    ) -> None:
        self._index = index
        self._project_ids_for = project_ids_for
        self._limits = limits

    def descriptors_for_project(
        self, project_id: str
    ) -> tuple[ArtifactDescriptor, ...]:
        found: list[ArtifactDescriptor] = []
        for descriptor in self._index.list_for_scope():
            if project_id in self._project_ids_for(descriptor.reference):
                found.append(descriptor)
        return tuple(found)

    def build(
        self, project_id: str
    ) -> tuple[
        ProjectKeyCatalogue,
        tuple[ApiOperationCatalogueEntry, ...],
        str | None,
    ]:
        """Return catalogues and an overflow diagnostic code when bounded out."""
        keys: list[str] = []
        api_ops: list[ApiOperationCatalogueEntry] = []
        seen_ops: set[tuple[str | None, str | None]] = set()
        for descriptor in self.descriptors_for_project(project_id):
            for key in descriptor.external_keys:
                if _KEY_PREFIX.fullmatch(key) is not None:
                    keys.append(key)
            if descriptor.kind in {
                ArtifactKind.API_SPEC,
                ArtifactKind.API_OPERATION,
            } or descriptor.parts:
                for part in descriptor.parts:
                    if part.kind != ArtifactKind.API_OPERATION:
                        continue
                    method_path = None
                    if " " in part.part_key:
                        method, _, path = part.part_key.partition(" ")
                        method_path = normalize_method_path(method, path)
                    entry = ApiOperationCatalogueEntry(
                        operation_id=part.operation_id,
                        method_path=method_path,
                    )
                    token = (entry.operation_id, entry.method_path)
                    if token in seen_ops:
                        continue
                    seen_ops.add(token)
                    api_ops.append(entry)

        unique_keys = tuple(sorted(set(keys)))
        prefixes = derive_prefixes(unique_keys)
        total_entries = len(unique_keys) + len(prefixes) + len(api_ops)
        if total_entries > self._limits.max_catalogue_entries:
            return (
                ProjectKeyCatalogue(keys=(), prefixes=()),
                (),
                "catalogue_overflow",
            )
        return (
            ProjectKeyCatalogue(keys=unique_keys, prefixes=prefixes),
            tuple(api_ops),
            None,
        )
