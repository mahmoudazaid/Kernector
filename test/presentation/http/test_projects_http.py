"""HTTP contract for /api/v1/projects (#372)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from composition.project.container import build_project_store
from domain.project.models import AssociationState, SourceAssociation, SourceScope
from infrastructure.config import load_settings
from presentation.http.app import create_app

_PROBLEM = "application/problem+json"
LIB = {"connector_id": "gh-1", "scope_kind": "repo", "scope_value": "acme/shared-lib"}


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
    assert client.get(f"/api/v1/projects/{project_id}").json()["associations"] == []
