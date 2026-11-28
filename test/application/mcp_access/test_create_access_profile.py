"""Create / list / get MCP access profiles via real SQLite (#324 Slice B)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from application.mcp_access.profiles import (
    CreateAccessProfile,
    CreateAccessProfileRequest,
    GetAccessProfile,
    ListAccessProfiles,
    SetAccessProfileExpiration,
)
from domain.mcp_access.errors import (
    InvalidAccessProfileExpirationError,
    ProjectNotInWorkspaceError,
)
from domain.mcp_access.models import McpAccessProfileStatus
from domain.project.models import Project
from domain.mcp_access.tokens import hash_access_token
from infrastructure.mcp_access.sql_store import SqlMcpAccessProfileStore
from infrastructure.project.sql_store import SqlProjectStore


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def project_store(catalog_path: Path) -> SqlProjectStore:
    store = SqlProjectStore(catalog_path, "ws-a")
    with store.transaction() as tx:
        tx.projects.add(Project("prj_alpha", "Alpha", "alpha", 1))
        tx.projects.add(Project("prj_beta", "Beta", "beta", 1))
    return store


@pytest.fixture
def profile_store(catalog_path: Path, project_store: SqlProjectStore) -> SqlMcpAccessProfileStore:
    _ = project_store
    return SqlMcpAccessProfileStore(catalog_path, "ws-a")


def test_create_returns_plaintext_once_and_default_deny_allowlist(
    profile_store: SqlMcpAccessProfileStore,
) -> None:
    create = CreateAccessProfile(store=profile_store)
    created = create.execute(
        CreateAccessProfileRequest(user_id='usr_test', project_id="prj_alpha", name="cursor-dev")
    )

    assert created.plaintext_token
    assert created.profile.profile_id.startswith("mcp_")
    assert created.profile.workspace_id == "ws-a"
    assert created.profile.project_id == "prj_alpha"
    assert created.profile.name == "cursor-dev"
    assert created.profile.allowlist == frozenset()
    assert created.profile.status == McpAccessProfileStatus.ACTIVE
    assert created.profile.expires_at is None
    assert "token" not in created.profile.__dataclass_fields__ or not hasattr(
        created.profile, "token"
    )

    listed = ListAccessProfiles(store=profile_store).execute()
    assert len(listed) == 1
    assert listed[0].profile_id == created.profile.profile_id
    assert not hasattr(listed[0], "plaintext_token")

    fetched = GetAccessProfile(store=profile_store).execute(created.profile.profile_id)
    assert fetched.profile_id == created.profile.profile_id
    assert fetched.allowlist == frozenset()

    matched = profile_store.authenticate(created.plaintext_token)
    assert matched is not None
    assert matched.profile_id == created.profile.profile_id
    assert matched.project_id == "prj_alpha"
    assert matched.allowlist == frozenset()

    assert profile_store.authenticate("not-the-token") is None
    # Stored form is a hash, not the plaintext.
    assert hash_access_token(created.plaintext_token) != created.plaintext_token


def test_multiple_profiles_may_bind_same_project(
    profile_store: SqlMcpAccessProfileStore,
) -> None:
    create = CreateAccessProfile(store=profile_store)
    first = create.execute(
        CreateAccessProfileRequest(user_id='usr_test', project_id="prj_alpha", name="cursor")
    )
    second = create.execute(
        CreateAccessProfileRequest(user_id='usr_test', project_id="prj_alpha", name="ci")
    )
    assert first.profile.profile_id != second.profile.profile_id
    assert {p.name for p in ListAccessProfiles(store=profile_store).execute()} == {
        "cursor",
        "ci",
    }


def test_create_rejects_project_from_other_workspace(catalog_path: Path) -> None:
    SqlProjectStore(catalog_path, "ws-a")
    with SqlProjectStore(catalog_path, "ws-b").transaction() as tx:
        tx.projects.add(Project("prj_other", "Other", "other", 1))

    store = SqlMcpAccessProfileStore(catalog_path, "ws-a")
    create = CreateAccessProfile(store=store)
    with pytest.raises(ProjectNotInWorkspaceError):
        create.execute(
            CreateAccessProfileRequest(user_id='usr_test', project_id="prj_other", name="bad")
        )


def test_create_normalizes_future_expires_at(
    profile_store: SqlMcpAccessProfileStore,
) -> None:
    future = (datetime.now(UTC) + timedelta(days=7)).replace(microsecond=0)
    created = CreateAccessProfile(store=profile_store).execute(
        CreateAccessProfileRequest(user_id='usr_test', 
            project_id="prj_alpha",
            name="expiring",
            expires_at=future.isoformat().replace("+00:00", "Z"),
        )
    )
    assert created.profile.expires_at == future.isoformat()
    assert profile_store.authenticate(created.plaintext_token) is not None


@pytest.mark.parametrize(
    "expires_at",
    [
        "next week",
        "12/01/2026",
        (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
    ],
)
def test_create_rejects_invalid_or_past_expires_at(
    profile_store: SqlMcpAccessProfileStore,
    expires_at: str,
) -> None:
    with pytest.raises(InvalidAccessProfileExpirationError):
        CreateAccessProfile(store=profile_store).execute(
            CreateAccessProfileRequest(user_id='usr_test', 
                project_id="prj_alpha",
                name="bad-expiry",
                expires_at=expires_at,
            )
        )
    assert ListAccessProfiles(store=profile_store).execute() == ()


def test_set_expiration_rejects_unparseable(
    profile_store: SqlMcpAccessProfileStore,
) -> None:
    created = CreateAccessProfile(store=profile_store).execute(
        CreateAccessProfileRequest(user_id='usr_test', project_id="prj_alpha", name="cursor")
    )
    with pytest.raises(InvalidAccessProfileExpirationError):
        SetAccessProfileExpiration(store=profile_store).execute(
            created.profile.profile_id, expires_at="not-a-date"
        )
