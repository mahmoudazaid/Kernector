"""Concurrent confirmations cannot bypass shared-scope acknowledgement (#372)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from application.project.associations import AssociateSource, AssociateSourceRequest
from domain.project.errors import SharedScopeConfirmationRequiredError
from domain.project.models import AssociationState, Project, SourceScope
from infrastructure.project.sql_store import SqlProjectStore

LIB = SourceScope("gh-1", "repo", "acme/shared-lib")


def _store(path: Path) -> SqlProjectStore:
    return SqlProjectStore(path, "ws-a")


def _seed(path: Path, *slugs: str) -> None:
    with _store(path).transaction() as tx:
        for slug in slugs:
            tx.projects.add(Project(f"prj_{slug}", slug.upper(), slug, 1))


def _associate(path: Path, project_id: str, acknowledged: frozenset[str]) -> str:
    AssociateSource(store=_store(path)).execute(
        AssociateSourceRequest(
            project_id=project_id,
            scope=LIB,
            roles=(),
            created_by="operator",
            acknowledged_shared_with=acknowledged,
        )
    )
    return project_id


def test_concurrent_unacknowledged_confirmations_leave_one_winner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    _seed(path, "a", "b")
    barrier = threading.Barrier(2)

    def run(project_id: str) -> str | Exception:
        barrier.wait(timeout=5)
        try:
            return _associate(path, project_id, frozenset())
        except SharedScopeConfirmationRequiredError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, "prj_a"), pool.submit(run, "prj_b")]
        outcomes = [future.result(timeout=15) for future in futures]

    winners = [o for o in outcomes if isinstance(o, str)]
    losers = [
        o for o in outcomes if isinstance(o, SharedScopeConfirmationRequiredError)
    ]
    assert len(winners) == 1 and len(losers) == 1
    assert losers[0].project_ids == tuple(winners)
    with _store(path).read() as tx:
        confirmed = [
            a.project_id
            for a in tx.associations.for_scope(LIB)
            if a.state is AssociationState.CONFIRMED
        ]
    assert confirmed == winners


def test_acknowledgement_made_before_a_concurrent_confirmation_is_stale(
    tmp_path: Path,
) -> None:
    path = tmp_path / "catalog.sqlite"
    _seed(path, "a", "b", "c")
    _associate(path, "prj_a", frozenset())
    _associate(path, "prj_c", frozenset({"prj_a"}))

    with pytest.raises(SharedScopeConfirmationRequiredError) as raised:
        _associate(path, "prj_b", frozenset({"prj_a"}))

    assert raised.value.project_ids == ("prj_a", "prj_c")
