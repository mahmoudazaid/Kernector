"""Trusted workspace selection and ProjectAccessCaller resolution (#447).

HTTP product requests derive the active workspace from the authenticated
principal and active memberships. ``DOCUMENT_CATALOG_WORKSPACE_ID`` is only an
explicit single-operator bootstrap constraint — never an implicit default and
never a substitute for membership verification.
"""

from __future__ import annotations

from domain.auth.ports import MembershipStore
from domain.auth.principal import Principal
from domain.project.access import ProjectAccessCaller
from infrastructure.config import Settings


class NoActiveMembershipError(Exception):
    """Principal has no active membership for the trusted workspace."""


class TrustedWorkspaceSelectionRequiredError(Exception):
    """Multiple active memberships and no validated session selection."""


def resolve_trusted_project_access_caller(
    principal: Principal,
    workspace_id: str,
    memberships: MembershipStore,
) -> ProjectAccessCaller:
    """Return a caller after verifying active membership.

    Args:
        principal: Authenticated principal (never from request body).
        workspace_id: Already-trusted server-selected workspace id.
        memberships: Membership store for verification.

    Returns:
        ProjectAccessCaller bound to *principal* and *workspace_id*.

    Raises:
        NoActiveMembershipError: No active membership for the pair.
    """
    membership = memberships.get_membership(principal.user_id, workspace_id)
    if membership is None or membership.status != "active":
        raise NoActiveMembershipError(
            "active workspace membership is required"
        )
    return ProjectAccessCaller(principal=principal, workspace_id=workspace_id)


def select_trusted_workspace(
    principal: Principal,
    memberships: MembershipStore,
    *,
    session_selected_workspace_id: str | None = None,
    bootstrap_workspace_id: str | None = None,
) -> str:
    """Select the trusted workspace for *principal*.

    Rules:
        - Bootstrap mode: constrain to ``bootstrap_workspace_id``; still
          require an active membership in that workspace.
        - Zero active memberships: deny.
        - One: auto-select.
        - Multiple: require ``session_selected_workspace_id`` that matches an
          active membership (never trust a raw client id as authorization).

    Args:
        principal: Authenticated principal.
        memberships: Membership store.
        session_selected_workspace_id: Server-side session selection when set.
        bootstrap_workspace_id: Explicit single-operator bootstrap workspace.

    Returns:
        Trusted workspace id.

    Raises:
        NoActiveMembershipError: Zero usable memberships or invalid selection.
        TrustedWorkspaceSelectionRequiredError: Multiple memberships without
            a validated session selection.
    """
    active = tuple(
        row
        for row in memberships.list_memberships(principal.user_id)
        if row.status == "active"
    )

    if bootstrap_workspace_id is not None:
        for row in active:
            if row.workspace_id == bootstrap_workspace_id:
                return bootstrap_workspace_id
        raise NoActiveMembershipError(
            "active membership required for bootstrap workspace"
        )

    if not active:
        raise NoActiveMembershipError("active workspace membership is required")

    if len(active) == 1:
        return active[0].workspace_id

    if session_selected_workspace_id is None:
        raise TrustedWorkspaceSelectionRequiredError(
            "workspace selection is required"
        )

    for row in active:
        if row.workspace_id == session_selected_workspace_id:
            return session_selected_workspace_id
    raise NoActiveMembershipError(
        "session workspace selection is not an active membership"
    )


def bootstrap_workspace_id_from_settings(settings: Settings) -> str | None:
    """Return env workspace when explicit bootstrap mode is enabled."""
    if not settings.auth.workspace_bootstrap:
        return None
    raw = settings.document_catalog.workspace_id
    if raw is None or not str(raw).strip():
        raise NoActiveMembershipError(
            "AUTH_WORKSPACE_BOOTSTRAP requires DOCUMENT_CATALOG_WORKSPACE_ID"
        )
    return str(raw).strip()


def resolve_caller_for_principal(
    principal: Principal,
    memberships: MembershipStore,
    *,
    session_selected_workspace_id: str | None = None,
    bootstrap_workspace_id: str | None = None,
) -> ProjectAccessCaller:
    """Select trusted workspace then resolve ``ProjectAccessCaller``."""
    workspace_id = select_trusted_workspace(
        principal,
        memberships,
        session_selected_workspace_id=session_selected_workspace_id,
        bootstrap_workspace_id=bootstrap_workspace_id,
    )
    return resolve_trusted_project_access_caller(
        principal, workspace_id, memberships
    )
