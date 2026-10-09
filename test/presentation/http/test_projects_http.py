"""HTTP contract for /api/v1/projects (#372)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from composition.project.container import build_project_store
from domain.project.models import AssociationState, SourceAssociation, SourceScope
from infrastructure.config import load_settings
from presentation.http.app import create_app

_PROBLEM = "application/problem+json"
LIB = {"connector_id": "gh-1", "scope_kind": "repo", "scope_value": "acme/shared-lib"}


@pytest.fixture(autouse=True)
def _no_pack_vocabulary_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "")


def _client() -> TestClient:
    return TestClient(create_app(cors_origins=()), raise_server_exceptions=False)


def _create(client: TestClient, slug: str) -> dict:
    response = client.post(
        "/api/v1/projects", json={"name": slug.upper(), "slug": slug}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _associate(client: TestClient, project_id: str, **extra: object):
    return client.post(
        f"/api/v1/projects/{project_id}/sources", json={**LIB, "roles": [], **extra}
    )


def _assert_problem(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith(_PROBLEM)
    body = response.json()
    assert body["code"] == code
    return body


def test_create_list_and_get_project() -> None:
    client = _client()

    created = _create(client, "oie")

    assert created["project_id"].startswith("prj_")
    assert created["version"] == 1
    assert "workspace_id" not in created
    listed = client.get("/api/v1/projects").json()
    assert [p["project_id"] for p in listed] == [created["project_id"]]
    detail = client.get(f"/api/v1/projects/{created['project_id']}").json()
    assert detail["slug"] == "oie"
    assert detail["associations"] == []
    assert detail["components"] == []
    assert detail["context_coverage"] == []


def test_detail_reports_context_coverage_with_pack_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    client = _client()
    project_id = _create(client, "oie")["project_id"]

    unknown = _associate(client, project_id, roles=["database"])
    _assert_problem(unknown, 422, "project_invalid_input")
    assert _associate(client, project_id, roles=["backend"]).status_code == 201

    coverage = client.get(f"/api/v1/projects/{project_id}").json()["context_coverage"]
    assert [c["status"] for c in coverage if c["context"] == "backend"] == [
        "associated"
    ]
    assert {c["context"]: c["status"] for c in coverage}["operations"] == (
        "not_associated"
    )
    backend = next(c for c in coverage if c["context"] == "backend")
    assert backend["scopes"] == [LIB]


def _seed_suggestion(project_id: str) -> None:
    with build_project_store(load_settings()).transaction() as tx:
        tx.associations.add(
            SourceAssociation(
                project_id,
                SourceScope(**LIB),
                (),
                AssociationState.SUGGESTED,
                (),
                "evidence",
                1,
            )
        )


def test_confirmed_associations_need_roles_with_pack_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    client = _client()
    project_id = _create(client, "oie")["project_id"]

    _assert_problem(_associate(client, project_id), 422, "project_invalid_input")
    _seed_suggestion(project_id)
    before = client.get(f"/api/v1/projects/{project_id}").json()
    url = f"/api/v1/projects/{project_id}/sources/confirm"
    omitted = client.post(url, json={**LIB, "expected_version": 1})
    empty = client.post(url, json={**LIB, "expected_version": 1, "roles": []})

    _assert_problem(omitted, 422, "project_invalid_input")
    _assert_problem(empty, 422, "project_invalid_input")
    after = client.get(f"/api/v1/projects/{project_id}").json()
    assert after == before
    assert [a["state"] for a in after["associations"]] == ["suggested"]
    assert after["components"] == []


def test_unknown_project_is_404() -> None:
    _assert_problem(
        _client().get("/api/v1/projects/prj_missing"), 404, "project_not_found"
    )


def test_duplicate_slug_is_409() -> None:
    client = _client()
    _create(client, "oie")

    response = client.post("/api/v1/projects", json={"name": "Again", "slug": "oie"})

    _assert_problem(response, 409, "project_slug_taken")


def test_invalid_slug_is_422() -> None:
    response = _client().post(
        "/api/v1/projects", json={"name": "X", "slug": "Bad Slug"}
    )

    _assert_problem(response, 422, "project_invalid_input")


def test_associate_source_is_confirmed() -> None:
    client = _client()
    project_id = _create(client, "oie")["project_id"]

    response = _associate(client, project_id)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["state"] == "confirmed"
    assert body["version"] == 1
    assert body["scope_value"] == "acme/shared-lib"
    (component,) = client.get(f"/api/v1/projects/{project_id}").json()["components"]
    assert component["reason"] == "association_default"
    assert component["members"] == [{**LIB, "path_prefix": ""}]


def test_associate_unknown_project_is_404() -> None:
    _assert_problem(_associate(_client(), "prj_missing"), 404, "project_not_found")


def test_shared_scope_requires_acknowledgement() -> None:
    client = _client()
    oie = _create(client, "oie")["project_id"]
    pay = _create(client, "pay")["project_id"]
    _associate(client, oie)

    body = _assert_problem(
        _associate(client, pay), 409, "shared_scope_confirmation_required"
    )

    assert [e["detail"] for e in body["errors"]] == [oie]
    assert body["errors"][0]["pointer"] == "/acknowledged_shared_with"
    acknowledged = _associate(client, pay, acknowledged_shared_with=[oie])
    assert acknowledged.status_code == 201


def test_confirm_suggestion_with_cas() -> None:
    client = _client()
    project_id = _create(client, "oie")["project_id"]
    with build_project_store(load_settings()).transaction() as tx:
        tx.associations.add(
            SourceAssociation(
                project_id,
                SourceScope(**LIB),
                (),
                AssociationState.SUGGESTED,
                (),
                "evidence",
                1,
            )
        )
    url = f"/api/v1/projects/{project_id}/sources/confirm"

    stale = client.post(url, json={**LIB, "expected_version": 5})
    _assert_problem(stale, 409, "project_version_conflict")
    confirmed = client.post(url, json={**LIB, "expected_version": 1})

    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["state"] == "confirmed"
    assert confirmed.json()["version"] == 2
    again = client.post(url, json={**LIB, "expected_version": 2})
    _assert_problem(again, 422, "project_invalid_input")


def test_confirm_unknown_association_is_404() -> None:
    client = _client()
    project_id = _create(client, "oie")["project_id"]

    response = client.post(
        f"/api/v1/projects/{project_id}/sources/confirm",
        json={**LIB, "expected_version": 1},
    )

    _assert_problem(response, 404, "association_not_found")


def test_remove_association_with_cas() -> None:
    client = _client()
    project_id = _create(client, "oie")["project_id"]
    _associate(client, project_id)
    url = f"/api/v1/projects/{project_id}/sources"

    stale = client.delete(url, params={**LIB, "expected_version": 3})
    _assert_problem(stale, 409, "project_version_conflict")
    removed = client.delete(url, params={**LIB, "expected_version": 1})

    assert removed.status_code == 204
    detail = client.get(f"/api/v1/projects/{project_id}").json()
    assert detail["associations"] == []
    assert detail["components"] == []


def test_replayed_delete_after_recreate_is_a_version_conflict() -> None:
    client = _client()
    project_id = _create(client, "oie")["project_id"]
    url = f"/api/v1/projects/{project_id}/sources"
    assert _associate(client, project_id).json()["version"] == 1
    stale_delete = {**LIB, "expected_version": 1}
    assert client.delete(url, params=stale_delete).status_code == 204
    recreated = _associate(client, project_id)
    assert recreated.status_code == 201, recreated.text
    before = client.get(f"/api/v1/projects/{project_id}").json()

    replay = client.delete(url, params=stale_delete)

    _assert_problem(replay, 409, "project_version_conflict")
    assert recreated.json()["version"] > 1
    after = client.get(f"/api/v1/projects/{project_id}").json()
    assert after == before
    assert after["associations"][0]["version"] == recreated.json()["version"]
    assert after["components"][0]["members"] == [{**LIB, "path_prefix": ""}]
