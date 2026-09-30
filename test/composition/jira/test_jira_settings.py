"""Jira connector settings loading; no live Atlassian calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.config import load_settings


def test_jira_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("JIRA_PAGE_SIZE", "JIRA_MAX_ISSUES", "JIRA_INCLUDE_COMMENTS"):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.jira.page_size == 100
    assert settings.jira.max_issues == 5000
    assert settings.jira.include_comments is False


def test_jira_values_are_parsed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("JIRA_PAGE_SIZE", "25")
    monkeypatch.setenv("JIRA_MAX_ISSUES", "50000")
    monkeypatch.setenv("JIRA_INCLUDE_COMMENTS", "true")
    monkeypatch.setenv("JIRA_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("JIRA_OAUTH_CLIENT_SECRET", "csecret")
    monkeypatch.setenv(
        "JIRA_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/connectors/jira/oauth/callback"
    )
    monkeypatch.setenv("JIRA_OAUTH_TOKEN_PATH", str(tmp_path / "jira-oauth-connection.json"))

    settings = load_settings()

    assert settings.jira.page_size == 25
    assert settings.jira.max_issues == 50000
    assert settings.jira.include_comments is True
    assert settings.jira_oauth.client_id == "cid"
    assert settings.jira_oauth.token_path == tmp_path / "jira-oauth-connection.json"
    assert "csecret" not in repr(settings.jira_oauth)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JIRA_MAX_ISSUES", "0"),
        ("JIRA_MAX_ISSUES", "-5"),
        ("JIRA_MAX_ISSUES", "50001"),
        ("JIRA_MAX_ISSUES", "lots"),
        ("JIRA_PAGE_SIZE", "0"),
        ("JIRA_PAGE_SIZE", "101"),
        ("JIRA_PAGE_SIZE", "ten"),
        ("JIRA_INCLUDE_COMMENTS", "maybe"),
    ],
)
def test_invalid_jira_limits_are_rejected(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=name):
        load_settings()


def test_in_repo_grant_path_must_stay_gitignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_OAUTH_TOKEN_PATH", "data/jira-token.json")

    with pytest.raises(ValueError, match="jira-oauth-"):
        load_settings()


_DC_VARS = (
    "JIRA_DC_BASE_URL",
    "JIRA_DC_TOKEN",
    "JIRA_DC_ALLOW_HTTP",
    "JIRA_DC_STATE_PATH",
    "JIRA_OAUTH_CLIENT_ID",
    "JIRA_OAUTH_CLIENT_SECRET",
    "JIRA_OAUTH_REDIRECT_URI",
    "JIRA_OAUTH_FRONTEND_REDIRECT",
)
DC_TOKEN = "dc-pat-secret-value"


@pytest.fixture
def clean_jira_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    for name in _DC_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_no_data_center_variables_means_cloud_mode(clean_jira_env: pytest.MonkeyPatch) -> None:
    assert load_settings().jira_data_center is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("JIRA_DC_ALLOW_HTTP", "true"),
        ("JIRA_DC_STATE_PATH", "data/jira-dc-custom.json"),
        ("JIRA_PAGE_SIZE", "10"),
        ("JIRA_MAX_ISSUES", "10"),
        ("JIRA_INCLUDE_COMMENTS", "true"),
    ],
)
def test_ancillary_and_shared_variables_do_not_activate_data_center_mode(
    clean_jira_env: pytest.MonkeyPatch, name: str, value: str
) -> None:
    clean_jira_env.setenv(name, value)

    assert load_settings().jira_data_center is None


def test_base_url_and_token_activate_a_complete_data_center_mode(
    clean_jira_env: pytest.MonkeyPatch,
) -> None:
    clean_jira_env.setenv("JIRA_DC_BASE_URL", "https://jira.example.com/jira/")
    clean_jira_env.setenv("JIRA_DC_TOKEN", DC_TOKEN)
    clean_jira_env.setenv("JIRA_PAGE_SIZE", "50")

    settings = load_settings()

    dc = settings.jira_data_center
    assert dc is not None
    assert dc.base_url == "https://jira.example.com/jira"
    assert dc.token == DC_TOKEN
    assert dc.configured is True
    assert dc.state_path.name == "jira-dc-connection.json"
    assert settings.jira.page_size == 50


@pytest.mark.parametrize(
    ("name", "value", "missing"),
    [
        ("JIRA_DC_BASE_URL", "https://jira.example.com", "token"),
        ("JIRA_DC_TOKEN", DC_TOKEN, "base_url"),
    ],
)
def test_partial_data_center_configuration_is_data_center_mode_needing_setup(
    clean_jira_env: pytest.MonkeyPatch, name: str, value: str, missing: str
) -> None:
    clean_jira_env.setenv(name, value)

    dc = load_settings().jira_data_center

    assert dc is not None
    assert getattr(dc, missing) is None
    assert dc.configured is False


@pytest.mark.parametrize("cloud_var", ["JIRA_OAUTH_CLIENT_ID", "JIRA_OAUTH_CLIENT_SECRET"])
def test_data_center_and_cloud_oauth_credentials_are_mutually_exclusive(
    clean_jira_env: pytest.MonkeyPatch, cloud_var: str
) -> None:
    clean_jira_env.setenv("JIRA_DC_TOKEN", DC_TOKEN)
    clean_jira_env.setenv(cloud_var, "cloud-value")

    with pytest.raises(ValueError, match="mutually exclusive") as caught:
        load_settings()

    assert DC_TOKEN not in str(caught.value)


def test_cloud_redirect_variables_alone_do_not_conflict_with_data_center(
    clean_jira_env: pytest.MonkeyPatch,
) -> None:
    clean_jira_env.setenv("JIRA_DC_BASE_URL", "https://jira.example.com")
    clean_jira_env.setenv(
        "JIRA_OAUTH_REDIRECT_URI", "http://localhost:8000/api/v1/connectors/jira/oauth/callback"
    )

    assert load_settings().jira_data_center is not None


@pytest.mark.parametrize(
    "url",
    [
        "http://jira.example.com",
        "ftp://jira.example.com",
        "jira.example.com",
        "https://",
        "https://user:pass@jira.example.com",
        "https://jira.example.com/?os_authType=basic",
        "https://jira.example.com/#top",
    ],
)
def test_invalid_data_center_base_urls_are_rejected(
    clean_jira_env: pytest.MonkeyPatch, url: str
) -> None:
    clean_jira_env.setenv("JIRA_DC_BASE_URL", url)

    with pytest.raises(ValueError, match="JIRA_DC_BASE_URL"):
        load_settings()


def test_plain_http_is_allowed_only_with_the_local_development_flag(
    clean_jira_env: pytest.MonkeyPatch,
) -> None:
    clean_jira_env.setenv("JIRA_DC_BASE_URL", "http://localhost:8080")
    clean_jira_env.setenv("JIRA_DC_ALLOW_HTTP", "true")

    dc = load_settings().jira_data_center

    assert dc is not None
    assert dc.base_url == "http://localhost:8080"
    assert dc.allow_http is True


def test_in_repo_data_center_state_path_must_stay_gitignored(
    clean_jira_env: pytest.MonkeyPatch,
) -> None:
    clean_jira_env.setenv("JIRA_DC_BASE_URL", "https://jira.example.com")
    clean_jira_env.setenv("JIRA_DC_STATE_PATH", "data/jira-state.json")

    with pytest.raises(ValueError, match="jira-dc-"):
        load_settings()


def test_data_center_token_is_masked_in_repr(clean_jira_env: pytest.MonkeyPatch) -> None:
    clean_jira_env.setenv("JIRA_DC_BASE_URL", "https://jira.example.com")
    clean_jira_env.setenv("JIRA_DC_TOKEN", DC_TOKEN)

    settings = load_settings()

    assert DC_TOKEN not in repr(settings.jira_data_center)
    assert DC_TOKEN not in repr(settings)
    assert "https://jira.example.com" in repr(settings.jira_data_center)
