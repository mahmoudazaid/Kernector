"""Workspace-bound project profile facade (#387 Phase A)."""

from __future__ import annotations

from collections.abc import Sequence

from packs.software_delivery.project_profile.models import TechnologyProfile
from packs.software_delivery.project_profile.reusable import ReusableComponentSource
from packs.software_delivery.project_profile.service import profile_project


class ProjectProfileFacade:
    """Pure client-supplied profiling bound to one workspace id for isolation."""

    def __init__(
        self,
        workspace_id: str,
        *,
        sources: Sequence[ReusableComponentSource] = (),
    ) -> None:
        self._workspace_id = workspace_id
        self._sources = tuple(sources)

    @property
    def workspace_id(self) -> str:
        return self._workspace_id

    def profile(
        self,
        evidence_groups: object,
        *,
        facets: Sequence[str] | None = None,
    ) -> TechnologyProfile:
        """Profile client-supplied evidence for this workspace binding."""
        return profile_project(
            evidence_groups,
            facets=facets,
            sources=self._sources,
        )
