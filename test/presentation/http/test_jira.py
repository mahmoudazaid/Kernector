"""Jira connector HTTP adapter — composition stubbed; no Atlassian network."""

from fastapi.testclient import TestClient

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from application.errors import (
    InputRejectedError,
    JiraDataCenterCredentialsRejectedError,
    JiraDataCenterModeError,
    JiraNotConnectedError,
    JiraReauthorizationRequiredError,
    JiraSetupRequiredError,
    JiraSiteSelectionRequiredError,
)
from composition import (
    JiraIssueLimitExceededError,
    JiraLastSync,
    JiraProjectItem,
    JiraProjectPage,
    JiraSelection,
    JiraSiteItem,
    JiraStatus,
)
from composition.errors import JiraConnectorError
from presentation.http.app import create_app
from presentation.http import deps

BASE = "/api/v1/connectors/jira"
ACME = JiraSiteItem(
    instance_id="cloud-acme",
    cloud_id="cloud-acme",
    name="Acme",
    url="https://acme.atlassian.net",
)


def _client(**overrides) -> TestClient:
    app = create_app()
    for dep, value in overrides.items():
        app.dependency_overrides[getattr(deps, dep)] = value
    return TestClient(app, follow_redirects=False)


def _raise(error: Exception):
    def _call(*_args, **_kwargs):
        raise error

    return _call


def test_status_is_presentation_safe() -> None:
    status = JiraStatus(
        available=True,
        oauth_ready=True,
        connected=True,
        account_name="Ada",
        site=ACME,
        project_keys=("ENG",),
        document_count=3,
        last_sync=JiraLastSync("2026-09-01T00:00:00+00:00", 1, 0, 2, 0, 0),
        connection_state="ready",
        sync_scope="Acme · ENG",
    )
    client = _client(get_jira_status=lambda: status)

    body = client.get(BASE).json()

    assert body["site"] == {
        "instance_id": "cloud-acme",
        "cloud_id": "cloud-acme",
        "name": "Acme",
        "url": ACME.url,
    }
    assert body["mode"] == "cloud"
    assert body["project_keys"] == ["ENG"]
    assert body["connection_state"] == "ready"
    assert body["last_sync"]["unchanged_count"] == 2
    assert not {"access_token", "refresh_token", "token"} & set(body)
    last = client.get(f"{BASE}/last-sync").json()
    assert last["new_count"] == 1


def test_oauth_start_and_callback_redirect() -> None:
    client = _client(
        get_jira_oauth_start=lambda: (lambda: "https://auth.atlassian.com/authorize?state=s"),
        get_jira_oauth_callback=lambda: (
            lambda state, code, error: f"http://localhost:3000/documents?jira={code}"
        ),
    )

    start = client.get(f"{BASE}/oauth/start")
    callback = client.get(f"{BASE}/oauth/callback", params={"state": "s", "code": "no_site"})

    assert start.status_code == 302
    assert start.headers["location"].startswith("https://auth.atlassian.com/authorize")
    assert callback.status_code == 302
    assert callback.headers["location"].endswith("jira=no_site")


def test_sites_list_and_select() -> None:
    seen: dict[str, str] = {}

    def _save(*, cloud_id: str) -> JiraSelection:
        seen["cloud_id"] = cloud_id
        return JiraSelection(site=ACME, project_keys=(), connector_id="c1")

    client = _client(
        get_jira_site_list=lambda: (lambda: (ACME,)),
        get_jira_site_write=lambda: _save,
    )

    sites = client.get(f"{BASE}/sites").json()
    saved = client.put(f"{BASE}/site", json={"cloud_id": "cloud-acme"})

    assert sites == {
        "items": [
            {
                "instance_id": "cloud-acme",
                "cloud_id": "cloud-acme",
                "name": "Acme",
                "url": ACME.url,
            }
        ]
    }
    assert saved.status_code == 200
    assert saved.json()["site"]["cloud_id"] == "cloud-acme"
    assert seen == {"cloud_id": "cloud-acme"}


def test_projects_page() -> None:
    seen: dict[str, int] = {}

    def _list(*, start_at: int = 0) -> JiraProjectPage:
        seen["start_at"] = start_at
        return JiraProjectPage(items=(JiraProjectItem("ENG", "Engineering"),), next_start_at=50)

    client = _client(get_jira_project_list=lambda: _list)

    body = client.get(f"{BASE}/projects", params={"start_at": 0}).json()

    assert body == {"items": [{"key": "ENG", "name": "Engineering"}], "next_start_at": 50}
    assert client.get(f"{BASE}/projects", params={"start_at": -1}).status_code == 422


def test_selection_read_and_write() -> None:
    seen: dict[str, object] = {}

    def _save(*, project_keys):
        seen["keys"] = tuple(project_keys)
        return JiraSelection(site=ACME, project_keys=tuple(project_keys), connector_id="c1")

    client = _client(
        get_jira_selection_read=lambda: (
            lambda: JiraSelection(site=ACME, project_keys=("ENG",), connector_id="c1")
        ),
        get_jira_selection_write=lambda: _save,
    )

    read = client.get(f"{BASE}/selection").json()
    written = client.put(f"{BASE}/selection", json={"project_keys": ["ENG", "OPS"]})

    assert read["project_keys"] == ["ENG"]
    assert written.json()["project_keys"] == ["ENG", "OPS"]
    assert seen["keys"] == ("ENG", "OPS")


def test_sync_projects_counts() -> None:
    client = _client(
        get_jira_sync=lambda: (
            lambda: ConnectorSyncResponse(
                outcomes=(ConnectorSyncOutcome("a", ConnectorSyncStatus.INGESTED, 2),)
            )
        )
    )

    body = client.post(f"{BASE}/sync").json()

    assert body["ingested_count"] == 1
    assert body["outcomes"][0]["source_id"] == "a"


def test_disconnect_returns_204() -> None:
    calls: list[bool] = []
    client = _client(get_jira_disconnect=lambda: (lambda: calls.append(True)))

    response = client.delete(BASE)

    assert response.status_code == 204
    assert calls == [True]


def test_typed_errors_map_to_problem_codes() -> None:
    cases = [
        ("get_jira_sync", JiraNotConnectedError("x"), 409, "jira_not_connected"),
        ("get_jira_sync", JiraReauthorizationRequiredError("x"), 409, "jira_reauthorization_required"),
        ("get_jira_sync", JiraSiteSelectionRequiredError("x"), 409, "jira_site_selection_required"),
        ("get_jira_sync", JiraIssueLimitExceededError("x"), 502, "jira_issue_limit_exceeded"),
        ("get_jira_sync", JiraConnectorError("secret body"), 502, "jira_request_failed"),
    ]
    for dep, error, status, code in cases:
        client = _client(**{dep: lambda error=error: _raise(error)})

        response = client.post(f"{BASE}/sync")

        assert response.status_code == status, code
        assert response.json()["code"] == code
        assert "secret" not in response.text


def test_rejected_selection_is_422() -> None:
    client = _client(
        get_jira_selection_write=lambda: _raise(InputRejectedError("A selected Jira project is inaccessible."))
    )

    response = client.put(f"{BASE}/selection", json={"project_keys": ["NOPE"]})

    assert response.status_code == 422


def test_selection_body_is_bounded() -> None:
    client = _client(get_jira_selection_write=lambda: _raise(AssertionError("not called")))

    response = client.put(f"{BASE}/selection", json={"project_keys": ["K"] * 101})

    assert response.status_code == 422


def test_data_center_status_has_mode_and_no_cloud_id() -> None:
    status = JiraStatus(
        available=True,
        oauth_ready=False,
        connected=True,
        site=JiraSiteItem(
            instance_id="SRV-1", name="Example Jira", url="https://jira.example.com"
        ),
        project_keys=("ENG",),
        connection_state="ready",
        mode="data_center",
    )
    client = _client(get_jira_status=lambda: status)

    body = client.get(BASE).json()

    assert body["mode"] == "data_center"
    assert body["oauth_ready"] is False
    assert body["site"] == {
        "instance_id": "SRV-1",
        "cloud_id": None,
        "name": "Example Jira",
        "url": "https://jira.example.com",
    }


def test_cloud_only_routes_in_data_center_mode_are_409() -> None:
    mode_error = JiraDataCenterModeError("Data Center mode")
    client = _client(
        get_jira_oauth_start=lambda: _raise(mode_error),
        get_jira_oauth_callback=lambda: _raise(mode_error),
        get_jira_site_list=lambda: _raise(mode_error),
        get_jira_site_write=lambda: _raise(mode_error),
    )

    responses = [
        client.get(f"{BASE}/oauth/start"),
        client.get(f"{BASE}/oauth/callback", params={"state": "s", "code": "c"}),
        client.get(f"{BASE}/sites"),
        client.put(f"{BASE}/site", json={"cloud_id": "cloud-acme"}),
    ]

    for response in responses:
        assert response.status_code == 409
        assert response.json()["code"] == "jira_data_center_mode"


def test_data_center_errors_map_to_fixed_problem_details() -> None:
    cases = [
        (JiraSetupRequiredError("secret url"), 409, "jira_setup_required", "JIRA_DC_BASE_URL"),
        (
            JiraDataCenterCredentialsRejectedError("secret token"),
            409,
            "jira_reauthorization_required",
            "JIRA_DC_TOKEN",
        ),
    ]
    for error, status, code, hint in cases:
        client = _client(get_jira_project_list=lambda error=error: _raise(error))

        response = client.get(f"{BASE}/projects")

        assert response.status_code == status, code
        body = response.json()
        assert body["code"] == code
        assert hint in body["detail"]
        assert "secret" not in response.text
