"""ProjectAccessPolicy port and trusted caller (#446 / #377)."""

from __future__ import annotations

import dataclasses

import pytest

from domain.auth.principal import Principal
from domain.project.access import ProjectAccessCaller, ProjectAccessPolicy


class _DenyAllPolicy:
    def can_read(self, caller: ProjectAccessCaller, project_id: str) -> bool:
        return False

    def readable_projects(self, caller: ProjectAccessCaller) -> tuple[str, ...]:
        return ()


class _AllowListedPolicy:
    def __init__(self, allowed: frozenset[str]) -> None:
        self._allowed = allowed

    def can_read(self, caller: ProjectAccessCaller, project_id: str) -> bool:
        return project_id in self._allowed

    def readable_projects(self, caller: ProjectAccessCaller) -> tuple[str, ...]:
        return tuple(sorted(self._allowed))


def test_project_access_caller_is_frozen_with_trusted_principal_and_workspace() -> None:
    principal = Principal(user_id="usr_alice", username="alice")
    caller = ProjectAccessCaller(principal=principal, workspace_id="ws_acme")
    assert caller.principal.user_id == "usr_alice"
    assert caller.workspace_id == "ws_acme"
    with pytest.raises(dataclasses.FrozenInstanceError):
        caller.workspace_id = "ws_other"  # type: ignore[misc]


def test_project_access_policy_can_deny_and_list_readable_projects() -> None:
    caller = ProjectAccessCaller(
        principal=Principal(user_id="usr_alice", username="alice"),
        workspace_id="ws_acme",
    )
    deny: ProjectAccessPolicy = _DenyAllPolicy()
    assert deny.can_read(caller, "prj_one") is False
    assert deny.readable_projects(caller) == ()

    allow: ProjectAccessPolicy = _AllowListedPolicy(frozenset({"prj_one", "prj_two"}))
    assert allow.can_read(caller, "prj_one") is True
    assert allow.can_read(caller, "prj_missing") is False
    assert allow.readable_projects(caller) == ("prj_one", "prj_two")
