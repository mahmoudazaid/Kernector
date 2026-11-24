"""Map SourceDocument metadata extras into provider-neutral structural facts."""

from __future__ import annotations

from pathlib import PurePosixPath

from domain.artifact.facts import ArtifactStructuralFacts
from domain.knowledge import SourceDocument
from infrastructure.artifact.openapi import extract_openapi_parts


def structural_facts_for(document: SourceDocument) -> ArtifactStructuralFacts:
    """Build classification facts from connector / upload metadata extras."""
    extra = document.metadata.extra
    path = ""
    github_path = extra.get("github_path")
    if isinstance(github_path, str) and github_path.strip():
        path = github_path
    else:
        file_name = extra.get("file_name")
        if isinstance(file_name, str) and file_name.strip():
            path = file_name
    filename = PurePosixPath(path.replace("\\", "/")).name if path else ""

    provider_type_field = ""
    issue_type = extra.get("jira_issue_type")
    if isinstance(issue_type, str):
        provider_type_field = issue_type

    association_roles: tuple[str, ...] = ()
    raw_roles = extra.get("association_roles", "")
    if isinstance(raw_roles, str) and raw_roles.strip():
        association_roles = tuple(
            part.strip() for part in raw_roles.split(",") if part.strip()
        )

    valid_spec_root = False
    name_lower = filename.lower()
    if name_lower.startswith("openapi.") or name_lower.startswith("swagger."):
        valid_spec_root = extract_openapi_parts(document).valid_spec_root

    return ArtifactStructuralFacts(
        path=path,
        filename=filename,
        provider_type_field=provider_type_field,
        association_roles=association_roles,
        valid_spec_root=valid_spec_root,
    )
