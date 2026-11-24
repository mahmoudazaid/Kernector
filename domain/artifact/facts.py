"""Structural facts for artifact context classification (no context literals)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ArtifactStructuralFacts:
    """Provider-neutral facts supplied by infrastructure extractors.

    Context tokens never appear here; packs match these fields with rules.
    """

    path: str = ""
    filename: str = ""
    provider_type_field: str = ""
    association_roles: tuple[str, ...] = ()
    valid_spec_root: bool = False
    path_prefix_roles: tuple[tuple[str, str], ...] = ()
