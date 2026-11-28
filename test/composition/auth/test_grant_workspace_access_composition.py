"""Composition grant_workspace_access (#446)."""

from __future__ import annotations

from pathlib import Path

import pytest

from application.errors import ConfigurationError
from composition.auth import clear_auth_store_cache, grant_workspace_access
from composition.auth.project_access import (
    MembershipGrantProjectAccessPolicy,
    _UnitOfWorkProjectLookup,
)
from domain.auth.principal import Principal
from domain.project.access import ProjectAccessCaller
from domain.project.models import Project
from infrastructure.auth.errors import AuthStoreError
from infrastructure.auth.sql_store import SqlAuthStore
from infrastructure.project.sql_store import ProjectStoreError, SqlProjectStore


def test_grant_workspace_access_validates_then_writes_atomically(
    tmp_path: Path,
) -> None:
    clear_auth_store_cache()
    auth = SqlAuthStore(tmp_path / "auth.sqlite")
    projects = SqlProjectStore(tmp_path / "catalog.sqlite", "ws_acme")
    user = auth.create_user("alice", "secret-password")
    with projects.transaction() as tx:
        tx.projects.add(Project("prj_one", "One", "one", 1))
        tx.projects.add(Project("prj_two", "Two", "two", 1))

    with pytest.raises(ConfigurationError, match="project"):
        grant_workspace_access(
            username="alice",
            project_ids=("prj_missing",),
            all_existing_projects=False,
            auth_store=auth,
            project_store=projects,
            workspace_id="ws_acme",
        )
    assert auth.get_membership(user.user_id, "ws_acme") is None

    result = grant_workspace_access(
        username="alice",
        project_ids=("prj_one",),
        all_existing_projects=False,
        auth_store=auth,
        project_store=projects,
        workspace_id="ws_acme",
    )
    assert result.project_ids == ("prj_one",)
    membership = auth.get_membership(user.user_id, "ws_acme")
    assert membership is not None
    assert membership.status == "active"
    grants = auth.list_project_grants(user.user_id, "ws_acme")
    assert [g.project_id for g in grants if g.status == "active"] == ["prj_one"]

    snap = grant_workspace_access(
        username="alice",
        project_ids=None,
        all_existing_projects=True,
        auth_store=auth,
        project_store=projects,
        workspace_id="ws_acme",
    )
    assert set(snap.project_ids) == {"prj_one", "prj_two"}

    policy = MembershipGrantProjectAccessPolicy(
        memberships=auth,
        grants=auth,
        projects=_UnitOfWorkProjectLookup(projects),
        bound_workspace_id="ws_acme",
    )
    caller = ProjectAccessCaller(
        principal=Principal(user_id=user.user_id, username="alice"),
        workspace_id="ws_acme",
    )
    assert policy.readable_projects(caller) == ("prj_one", "prj_two")


def test_grant_workspace_access_rejects_empty_project_selection(
    tmp_path: Path,
) -> None:
    auth = SqlAuthStore(tmp_path / "auth.sqlite")
    projects = SqlProjectStore(tmp_path / "catalog.sqlite", "ws_acme")
    auth.create_user("alice", "secret-password")
    with pytest.raises(ConfigurationError, match="project"):
        grant_workspace_access(
            username="alice",
            project_ids=None,
            all_existing_projects=False,
            auth_store=auth,
            project_store=projects,
            workspace_id="ws_acme",
        )
    with pytest.raises(ConfigurationError, match="project"):
        grant_workspace_access(
            username="alice",
            project_ids=(),
            all_existing_projects=False,
            auth_store=auth,
            project_store=projects,
            workspace_id="ws_acme",
        )


def test_grant_workspace_access_empty_catalog_grants_membership_only(
    tmp_path: Path,
) -> None:
    """--all-existing-projects on an empty catalog enables first project create."""
    auth = SqlAuthStore(tmp_path / "auth.sqlite")
    projects = SqlProjectStore(tmp_path / "catalog.sqlite", "ws_acme")
    user = auth.create_user("alice", "secret-password")
    result = grant_workspace_access(
        username="alice",
        project_ids=None,
        all_existing_projects=True,
        auth_store=auth,
        project_store=projects,
        workspace_id="ws_acme",
    )
    assert result.project_ids == ()
    membership = auth.get_membership(user.user_id, "ws_acme")
    assert membership is not None
    assert membership.status == "active"


def test_grant_workspace_access_maps_auth_store_build_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clear_auth_store_cache()
    projects = SqlProjectStore(tmp_path / "catalog.sqlite", "ws_acme")
    with projects.transaction() as tx:
        tx.projects.add(Project("prj_one", "One", "one", 1))

    def _boom(_settings=None):
        raise FileExistsError(f"{tmp_path / 'notadir'}: not a directory")

    monkeypatch.setattr("composition.auth.build_auth_store", _boom)
    with pytest.raises(ConfigurationError, match="not a directory"):
        grant_workspace_access(
            username="alice",
            project_ids=("prj_one",),
            all_existing_projects=False,
            project_store=projects,
            workspace_id="ws_acme",
        )


def test_grant_workspace_access_maps_project_store_errors(
    tmp_path: Path,
) -> None:
    auth = SqlAuthStore(tmp_path / "auth.sqlite")
    auth.create_user("alice", "secret-password")

    class _BoomProjects:
        def read(self):
            raise ProjectStoreError("could not apply project migrations")

    with pytest.raises(ConfigurationError, match="project migrations"):
        grant_workspace_access(
            username="alice",
            project_ids=("prj_one",),
            all_existing_projects=False,
            auth_store=auth,
            project_store=_BoomProjects(),
            workspace_id="ws_acme",
        )


def test_grant_workspace_access_maps_auth_store_lookup_errors(
    tmp_path: Path,
) -> None:
    projects = SqlProjectStore(tmp_path / "catalog.sqlite", "ws_acme")
    with projects.transaction() as tx:
        tx.projects.add(Project("prj_one", "One", "one", 1))

    class _BoomAuth:
        def get_user_by_username(self, username: str):
            raise AuthStoreError("auth sqlite unavailable")

        def grant_membership_with_projects(self, *args, **kwargs):
            raise AssertionError("should not grant after lookup failure")

    with pytest.raises(ConfigurationError, match="auth sqlite unavailable"):
        grant_workspace_access(
            username="alice",
            project_ids=("prj_one",),
            all_existing_projects=False,
            auth_store=_BoomAuth(),  # type: ignore[arg-type]
            project_store=projects,
            workspace_id="ws_acme",
        )
