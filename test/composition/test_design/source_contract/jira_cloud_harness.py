"""Jira Cloud contract harness over the production source composition."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from composition import container as composition_container
from composition.test_design.sources import TestDesignSource
from domain.errors import ConnectorAuthError, ConnectorNotFoundError
from infrastructure.config import Settings, load_settings
from infrastructure.connectors.jira.client import HttpJiraClient
from infrastructure.connectors.jira.oauth import JiraOAuthConnectionStore
from test.composition.jira.jira_fakes import ACME, FakeGateway, connection, jira_settings, stores

SENTINEL_TOKEN = "SENTINEL-TOKEN-cloud-7f3a9c"


def _refuse_construction(*_args: object, **_kwargs: object) -> None:
    raise AssertionError("contract tests must not build a real Jira HTTP client")


class _ScriptedIssueClient:
    def __init__(self, harness: JiraCloudContractHarness) -> None:
        self._harness = harness

    def get_issue(self, key: str, fields: Sequence[str]) -> Mapping[str, object]:
        return self._harness._respond(key, fields)


class JiraCloudContractHarness:
    """``SourceContractHarness`` for Jira Cloud issues."""

    provider = "jira"
    source_type = "jira"
    raw_locators = (
        "ENG-7",
        " eng-7 ",
        "https://acme.atlassian.net/browse/ENG-7",
    )
    canonical_locator = "ENG-7"
    invalid_locators = (
        "",
        "7",
        "acme/app#7",
        "https://other.example.com/browse/ENG-7",
    )

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(HttpJiraClient, "__init__", _refuse_construction)
        self._settings: Settings = replace(
            jira_settings(load_settings(), tmp_path), jira_data_center=None
        )
        _states, self._store = stores(self._settings)
        self._store.save(
            connection(
                access_token=SENTINEL_TOKEN,
                project_keys=("ENG",),
                site=ACME,
            )
        )
        self._gateway = FakeGateway()
        self._calls = 0
        self._description = "Acceptance criteria: login, lockout, password length."
        self._numeric_ids = {"item-1": "10001"}
        self._item_id = "10001"
        self._failure: Exception | None = None

    @property
    def upstream_calls(self) -> int:
        return self._calls

    def source(self) -> TestDesignSource:
        return composition_container.build_test_design_sources(
            self._settings,
            jira_cloud_connection_store=self._store,
            jira_cloud_gateway=self._gateway,
            jira_cloud_client_factory=lambda _token, _cloud_id: _ScriptedIssueClient(self),
        ).resolve(self.provider)

    def serve(self, body: str, *, item_id: str = "item-1") -> None:
        self._description = body
        self._item_id = self._numeric_ids.setdefault(
            item_id, str(10001 + len(self._numeric_ids))
        )
        self._failure = None

    def disconnect(self) -> None:
        self._store.clear()

    def reject_auth(self) -> None:
        stored = self._store.load()
        assert stored is not None
        self._store.save(replace(stored, reauthorization_required=True, access_token=None))

    def fail_not_found(self) -> None:
        self._failure = ConnectorNotFoundError("The Jira resource was not found.")

    def _respond(self, key: str, fields: Sequence[str]) -> Mapping[str, object]:
        self._calls += 1
        if self._failure is not None:
            raise self._failure
        return {
            "id": self._item_id,
            "key": key,
            "fields": {
                "summary": "Login",
                "description": self._description,
                "updated": "2026-09-14T12:00:00.000+0000",
            },
        }
