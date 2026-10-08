"""XRAY_* environment loading: disabled by default, validated, secrets masked."""

from __future__ import annotations

import pytest

from infrastructure.config import XraySettings, load_settings

SECRET = "xray-client-secret-XYZ"


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in (
        "XRAY_DEPLOYMENT",
        "XRAY_PROJECT_KEY",
        "XRAY_LINK_TYPE",
        "XRAY_CLIENT_ID",
        "XRAY_CLIENT_SECRET",
        "XRAY_CLOUD_BASE_URL",
        "JIRA_OAUTH_CLIENT_ID",
        "JIRA_OAUTH_CLIENT_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _cloud(env: pytest.MonkeyPatch) -> None:
    env.setenv("XRAY_DEPLOYMENT", "cloud")
    env.setenv("XRAY_PROJECT_KEY", "QA")
    env.setenv("XRAY_CLIENT_ID", "client-id")
    env.setenv("XRAY_CLIENT_SECRET", SECRET)


def test_xray_is_disabled_by_default(env: pytest.MonkeyPatch) -> None:
    xray = load_settings().xray

    assert xray == XraySettings()
    assert xray.configured is False


def test_cloud_settings_load_with_defaults(env: pytest.MonkeyPatch) -> None:
    _cloud(env)

    xray = load_settings().xray

    assert xray.configured is True
    assert xray.deployment == "cloud"
    assert xray.project_key == "QA"
    assert xray.link_type == "Test"
    assert xray.client_id == "client-id"
    assert xray.client_secret == SECRET
    assert xray.cloud_base_url == "https://xray.cloud.getxray.app"
    assert SECRET not in repr(xray)


def test_deployment_and_link_type_are_normalised(env: pytest.MonkeyPatch) -> None:
    _cloud(env)
    env.setenv("XRAY_DEPLOYMENT", " Cloud ")
    env.setenv("XRAY_LINK_TYPE", " Tests ")

    xray = load_settings().xray

    assert (xray.deployment, xray.link_type) == ("cloud", "Tests")


def test_blank_link_type_disables_linking(env: pytest.MonkeyPatch) -> None:
    _cloud(env)
    env.setenv("XRAY_LINK_TYPE", " ")

    assert load_settings().xray.link_type == ""


@pytest.mark.parametrize("missing", ["XRAY_PROJECT_KEY", "XRAY_CLIENT_ID", "XRAY_CLIENT_SECRET"])
def test_cloud_requires_project_and_credentials(env: pytest.MonkeyPatch, missing: str) -> None:
    _cloud(env)
    env.delenv(missing)

    with pytest.raises(ValueError, match=missing) as caught:
        load_settings()

    assert SECRET not in str(caught.value)


@pytest.mark.parametrize("key", ["qa", "Q-A", "1QA", "QA PROJECT"])
def test_project_key_must_be_a_jira_project_key(env: pytest.MonkeyPatch, key: str) -> None:
    _cloud(env)
    env.setenv("XRAY_PROJECT_KEY", key)

    with pytest.raises(ValueError, match="XRAY_PROJECT_KEY"):
        load_settings()


def test_unknown_deployment_is_rejected(env: pytest.MonkeyPatch) -> None:
    env.setenv("XRAY_DEPLOYMENT", "hybrid")

    with pytest.raises(ValueError, match="XRAY_DEPLOYMENT"):
        load_settings()


@pytest.mark.parametrize(
    "url", ["http://xray.example.test", "https://user:pw@xray.example.test", "https://x?y=1"]
)
def test_cloud_base_url_must_be_plain_https(env: pytest.MonkeyPatch, url: str) -> None:
    _cloud(env)
    env.setenv("XRAY_CLOUD_BASE_URL", url)

    with pytest.raises(ValueError, match="XRAY_CLOUD_BASE_URL"):
        load_settings()


def test_server_requires_jira_data_center(env: pytest.MonkeyPatch) -> None:
    env.setenv("XRAY_DEPLOYMENT", "server")
    env.setenv("XRAY_PROJECT_KEY", "QA")

    with pytest.raises(ValueError, match="JIRA_DC_BASE_URL"):
        load_settings()


def test_server_reuses_jira_data_center_credentials(env: pytest.MonkeyPatch) -> None:
    env.setenv("XRAY_DEPLOYMENT", "server")
    env.setenv("XRAY_PROJECT_KEY", "QA")
    env.setenv("JIRA_DC_BASE_URL", "https://jira.example.test")
    env.setenv("JIRA_DC_TOKEN", "dc-token")

    settings = load_settings()

    assert settings.xray.configured is True
    assert settings.xray.deployment == "server"
    assert settings.xray.client_secret is None
