"""Token lifecycle for MCP access profiles via real SQLite (#324 Slice C)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from application.mcp_access.profiles import (
    CreateAccessProfile,
    CreateAccessProfileRequest,
    DisableAccessProfile,
    RevokeAccessProfile,
    RotateAccessProfileToken,
    SetAccessProfileExpiration,
)
from domain.mcp_access.models import McpAccessProfileStatus
from domain.project.models import Project
from infrastructure.mcp_access.sql_store import SqlMcpAccessProfileStore
from infrastructure.project.sql_store import SqlProjectStore


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog.sqlite"


@pytest.fixture
def profile_store(catalog_path: Path) -> SqlMcpAccessProfileStore:
    projects = SqlProjectStore(catalog_path, "ws-a")
    with projects.transaction() as tx:
        tx.projects.add(Project("prj_alpha", "Alpha", "alpha", 1))
    return SqlMcpAccessProfileStore(catalog_path, "ws-a")


def _create(store: SqlMcpAccessProfileStore):
    return CreateAccessProfile(store=store).execute(
        CreateAccessProfileRequest(project_id="prj_alpha", name="cursor")
    )


def test_rotate_invalidates_old_token_immediately(
    profile_store: SqlMcpAccessProfileStore,
) -> None:
    created = _create(profile_store)
    old = created.plaintext_token
    rotated = RotateAccessProfileToken(store=profile_store).execute(
        created.profile.profile_id
    )
    assert rotated.plaintext_token != old
    assert profile_store.authenticate(old) is None
    assert profile_store.authenticate(rotated.plaintext_token) is not None


def test_disable_and_revoke_reject_authentication(
    profile_store: SqlMcpAccessProfileStore,
) -> None:
    created = _create(profile_store)
    DisableAccessProfile(store=profile_store).execute(created.profile.profile_id)
    assert profile_store.authenticate(created.plaintext_token) is None
    disabled = profile_store.get(created.profile.profile_id)
    assert disabled is not None
    assert disabled.status == McpAccessProfileStatus.DISABLED

    other = _create(profile_store)
    RevokeAccessProfile(store=profile_store).execute(other.profile.profile_id)
    assert profile_store.authenticate(other.plaintext_token) is None
    revoked = profile_store.get(other.profile.profile_id)
    assert revoked is not None
    assert revoked.status == McpAccessProfileStatus.REVOKED


def test_expired_profile_cannot_authenticate(
    profile_store: SqlMcpAccessProfileStore,
) -> None:
    created = _create(profile_store)
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    SetAccessProfileExpiration(store=profile_store).execute(
        created.profile.profile_id, expires_at=past
    )
    assert profile_store.authenticate(created.plaintext_token) is None


def test_lifecycle_survives_store_reopen(catalog_path: Path) -> None:
    first = SqlMcpAccessProfileStore(catalog_path, "ws-a")
    SqlProjectStore(catalog_path, "ws-a")
    with SqlProjectStore(catalog_path, "ws-a").transaction() as tx:
        tx.projects.add(Project("prj_alpha", "Alpha", "alpha", 1))
    first = SqlMcpAccessProfileStore(catalog_path, "ws-a")
    created = _create(first)
    RevokeAccessProfile(store=first).execute(created.profile.profile_id)

    reopened = SqlMcpAccessProfileStore(catalog_path, "ws-a")
    assert reopened.authenticate(created.plaintext_token) is None
    loaded = reopened.get(created.profile.profile_id)
    assert loaded is not None
    assert loaded.status == McpAccessProfileStatus.REVOKED


def test_plaintext_token_never_logged(
    profile_store: SqlMcpAccessProfileStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        created = _create(profile_store)
        RotateAccessProfileToken(store=profile_store).execute(
            created.profile.profile_id
        )
        RevokeAccessProfile(store=profile_store).execute(created.profile.profile_id)
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert created.plaintext_token not in joined
