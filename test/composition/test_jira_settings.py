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
