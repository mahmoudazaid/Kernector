"""Offline fakes for Jira composition tests: no Atlassian calls, no live tokens."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from domain.errors import ConnectorAuthError, ConnectorNotFoundError
from infrastructure.config import (
    JiraDataCenterSettings,
    JiraOAuthSettings,
    JiraSettings,
    Settings,
)
from infrastructure.connectors.jira.client import (
    JiraIssuePage,
    JiraProject,
    JiraProjectPage,
)
from infrastructure.connectors.jira.data_center_state import JiraDataCenterStateStore
from infrastructure.connectors.jira.oauth import (
    AccessibleResource,
    JiraOAuthConnection,
    JiraOAuthConnectionStore,
    JiraOAuthGrant,
    JiraOAuthStateStore,
)
from infrastructure.connectors.jira.site import JiraSite

SECRET = "atl-secret-token-value"
READ = ("read:jira-work", "read:me")

ACME = JiraSite(cloud_id="cloud-acme", site_url="https://acme.atlassian.net", name="Acme")
BETA = JiraSite(cloud_id="cloud-beta", site_url="https://beta.atlassian.net", name="Beta")


def resource(site: JiraSite, scopes: Sequence[str] = READ) -> AccessibleResource:
    return AccessibleResource(
        id=site.cloud_id, name=site.name, url=site.site_url, scopes=tuple(scopes)
    )


def jira_settings(base: Settings, tmp_path: Path, **jira: object) -> Settings:
    return replace(
        base,
        jira=JiraSettings(**jira),  # type: ignore[arg-type]
        jira_oauth=JiraOAuthSettings(
            client_id="client-id",
            client_secret="client-secret",
            redirect_uri="http://127.0.0.1:8000/api/v1/connectors/jira/oauth/callback",
            frontend_redirect="http://localhost:3000/documents",
            token_path=tmp_path / "jira-oauth-connection.json",
            state_path=tmp_path / "jira-oauth-state.json",
            state_ttl_seconds=600,
        ),
    )


def stores(settings: Settings) -> tuple[JiraOAuthStateStore, JiraOAuthConnectionStore]:
    oauth = settings.jira_oauth
    return (
        JiraOAuthStateStore(oauth.state_path, ttl_seconds=oauth.state_ttl_seconds),
        JiraOAuthConnectionStore(oauth.token_path),
    )


def connection(**overrides: object) -> JiraOAuthConnection:
    values: dict[str, object] = {
        "access_token": f"{SECRET}-access-0",
        "refresh_token": f"{SECRET}-refresh-0",
        "access_token_expires_at": 4_000_000_000.0,
        "account_name": "Ada",
        "site": ACME,
        "project_keys": ("ENG",),
        "connector_id": "conn-1",
    }
    values.update(overrides)
    return JiraOAuthConnection(**values)  # type: ignore[arg-type]


@dataclass
class FakeGateway:
    """Rotating refresh by default; queue exceptions or grants in ``refresh_results``."""

    resources: list[AccessibleResource] = field(default_factory=lambda: [resource(ACME)])
    refresh_results: list[JiraOAuthGrant | Exception] = field(default_factory=list)
    rejected_tokens: set[str] = field(default_factory=set)
    exchange_error: Exception | None = None
    refresh_calls: list[str] = field(default_factory=list)
    on_refresh: Callable[[], None] | None = None
    on_fetch: Callable[[str], None] | None = None
    fetch_tokens: list[str] = field(default_factory=list)

    def exchange_code(self, code: str) -> JiraOAuthGrant:
        if self.exchange_error is not None:
            raise self.exchange_error
        assert code == "code"
        return JiraOAuthGrant(
            access_token=f"{SECRET}-access-0",
            refresh_token=f"{SECRET}-refresh-0",
            expires_in=3600,
        )

    def refresh(self, refresh_token: str) -> JiraOAuthGrant:
        self.refresh_calls.append(refresh_token)
        if self.on_refresh is not None:
            self.on_refresh()
        if self.refresh_results:
            result = self.refresh_results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result
        n = len(self.refresh_calls)
        return JiraOAuthGrant(
            access_token=f"{SECRET}-access-{n}",
            refresh_token=f"{SECRET}-refresh-{n}",
            expires_in=3600,
        )

    def fetch_accessible_resources(self, access_token: str) -> tuple[AccessibleResource, ...]:
        self.fetch_tokens.append(access_token)
        if self.on_fetch is not None:
            self.on_fetch(access_token)
        if access_token in self.rejected_tokens:
            raise ConnectorAuthError("rejected")
        return tuple(self.resources)

    def fetch_account_name(self, access_token: str) -> str | None:
        return "Ada"


def issue(key: str, updated: str = "2026-09-01T10:00:00.000+0000") -> dict[str, object]:
    return {
        "id": key.replace("-", ""),
        "key": key,
        "fields": {"summary": f"Summary of {key}", "updated": updated},
    }


@dataclass
class FakeJiraClient:
    """One fake site. Projects map key -> issues; tokens in ``rejected`` fail auth."""

    projects: Mapping[str, Sequence[Mapping[str, object]]] = field(
        default_factory=lambda: {"ENG": [issue("ENG-1")], "OPS": [issue("OPS-1")]}
    )
    rejected: set[str] = field(default_factory=set)
    calls: list[tuple[str, str]] = field(default_factory=list)
    error: Exception | None = None

    def factory(self, access_token: str, cloud_id: str) -> _BoundClient:
        self.calls.append((access_token, cloud_id))
        return _BoundClient(self, access_token)


@dataclass
class _BoundClient:
    owner: FakeJiraClient
    token: str

    def _check(self) -> None:
        if self.token in self.owner.rejected:
            raise ConnectorAuthError("rejected")
        if self.owner.error is not None:
            raise self.owner.error

    def search_issues(
        self,
        jql: str,
        fields: Sequence[str],
        page_size: int,
        next_page_token: str | None,
    ) -> JiraIssuePage:
        self._check()
        key = jql.split('"')[1]
        return JiraIssuePage(
            issues=tuple(self.owner.projects.get(key, ())), next_page_token=None, is_last=True
        )

    def list_projects(self, *, start_at: int, max_results: int) -> JiraProjectPage:
        self._check()
        keys = sorted(self.owner.projects)
        chunk = keys[start_at : start_at + max_results]
        is_last = start_at + len(chunk) >= len(keys)
        return JiraProjectPage(
            items=tuple(JiraProject(key=k, name=f"{k} project") for k in chunk),
            is_last=is_last,
            next_start_at=None if is_last else start_at + len(chunk),
        )

    def get_project(self, key: str) -> JiraProject:
        self._check()
        if key not in self.owner.projects:
            raise ConnectorNotFoundError("missing")
        return JiraProject(key=key, name=f"{key} project")


DC_TOKEN = "dc-personal-access-token-secret"
DC_BASE_URL = "https://jira.example.com/jira"
DC_SITE = JiraSite(cloud_id="SRV-1", site_url=DC_BASE_URL, name="Example Jira")
DC_OTHER_SITE = JiraSite(cloud_id="SRV-2", site_url=DC_BASE_URL, name="Migrated Jira")


def dc_settings(
    base: Settings,
    tmp_path: Path,
    *,
    base_url: str | None = DC_BASE_URL,
    token: str | None = DC_TOKEN,
    **jira: object,
) -> Settings:
    return replace(
        base,
        jira=JiraSettings(**jira),  # type: ignore[arg-type]
        jira_oauth=JiraOAuthSettings(
            token_path=tmp_path / "jira-oauth-connection.json",
            state_path=tmp_path / "jira-oauth-state.json",
        ),
        jira_data_center=JiraDataCenterSettings(
            base_url=base_url,
            token=token,
            state_path=tmp_path / "jira-dc-connection.json",
        ),
    )


def dc_store(settings: Settings) -> JiraDataCenterStateStore:
    assert settings.jira_data_center is not None
    return JiraDataCenterStateStore(settings.jira_data_center.state_path)


@dataclass
class FakeDataCenterClient:
    """One fake Data Center instance; ``pages`` scripts search responses per project."""

    projects: Mapping[str, Sequence[Mapping[str, object]]] = field(
        default_factory=lambda: {"ENG": [issue("ENG-1")], "OPS": [issue("OPS-1")]}
    )
    site: JiraSite = DC_SITE
    reject: bool = False
    error: Exception | None = None
    server_info_error: Exception | None = None
    project_error: Exception | None = None
    pages: Mapping[str, Sequence[JiraIssuePage]] | None = None
    built: list[tuple[str, str]] = field(default_factory=list)
    request_count: int = 0
    _search_calls: dict[str, int] = field(default_factory=dict)

    def factory(self, base_url: str, token: str) -> FakeDataCenterClient:
        self.built.append((base_url, token))
        return self

    def _check(self) -> None:
        self.request_count += 1
        if self.reject:
            raise ConnectorAuthError("rejected")
        if self.error is not None:
            raise self.error

    def server_info(self) -> JiraSite:
        self._check()
        if self.server_info_error is not None:
            raise self.server_info_error
        return self.site

    def search_issues(
        self,
        jql: str,
        fields: Sequence[str],
        page_size: int,
        next_page_token: str | None,
    ) -> JiraIssuePage:
        self._check()
        key = jql.split('"')[1]
        if self.pages is not None:
            index = self._search_calls.get(key, 0)
            self._search_calls[key] = index + 1
            return self.pages[key][index]
        issues = tuple(self.projects.get(key, ()))
        return JiraIssuePage(
            issues=issues, next_page_token=None, is_last=True, total=len(issues)
        )

    def list_projects(self, *, start_at: int, max_results: int) -> JiraProjectPage:
        self._check()
        keys = sorted(self.projects)
        chunk = keys[start_at : start_at + max_results]
        is_last = start_at + len(chunk) >= len(keys)
        return JiraProjectPage(
            items=tuple(JiraProject(key=k, name=f"{k} project") for k in chunk),
            is_last=is_last,
            next_start_at=None if is_last else start_at + len(chunk),
        )

    def get_project(self, key: str) -> JiraProject:
        self._check()
        if self.project_error is not None:
            raise self.project_error
        if key not in self.projects:
            raise ConnectorNotFoundError("missing")
        return JiraProject(key=key, name=f"{key} project")
