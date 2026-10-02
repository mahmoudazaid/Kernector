"""Jira Data Center Test Design source specifics, through the composed registry (#353)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from application.errors import (
    InsufficientEvidenceError,
    SourceNotConnectedError,
    SourceReauthorizationRequiredError,
)
from composition import container as composition_container
from composition.test_design.errors import (
    TestDesignUnavailableError,
    TestDesignValidationError,
)
from composition.test_design.facade import (
    CreateTestDesignDraftRequest,
    PatchTestDesignDraftRequest,
    SourceLocatorView,
)
from composition.test_design.sources import TestDesignSource, TestDesignSourceRegistry
from domain.errors import (
    ConnectorError,
    ConnectorNetworkError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
)
from domain.knowledge import SourceDocument, SourceLocator
from infrastructure.config import Settings, load_settings
from infrastructure.connectors.jira.data_center_state import (
    JiraDataCenterState,
    JiraDataCenterStateStore,
)
from infrastructure.connectors.jira.errors import JiraPaginationError, JiraRateLimitError
from test.composition.jira.jira_fakes import DC_SITE, dc_settings
from test.composition.test_design.test_design_fakes import build_fake_facade

AC_FIELD = "customfield_10200"
PAYLOAD_SENTINEL = "RAW-PAYLOAD-SENTINEL"


class FakeIssueClient:
    """Serves one issue payload; counts requests; raises ``error`` when set."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []
        self.error: Exception | None = None
        self.fields: dict[str, object] = {
            "summary": "Login",
            "description": "Users log in with *email*.",
            "updated": "2026-09-14T12:00:00.000+0000",
            AC_FIELD: "Lockout after 5 attempts.",
        }
        self.issue_id = "10001"
        self.key: str | None = None

    def get_issue(self, key: str, fields: Sequence[str]) -> Mapping[str, object]:
        self.calls.append((key, tuple(fields)))
        if self.error is not None:
            raise self.error
        return {
            "id": self.issue_id,
            "key": self.key or key,
            "fields": {name: value for name, value in self.fields.items() if name in fields},
        }


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.client = FakeIssueClient()
        self.settings: Settings = dc_settings(load_settings(), tmp_path)
        assert self.settings.jira_data_center is not None
        self.settings = replace(
            self.settings,
            jira_data_center=replace(
                self.settings.jira_data_center, acceptance_criteria_field=AC_FIELD
            ),
        )
        self.store = JiraDataCenterStateStore(tmp_path / "jira-dc-connection.json")
        self.client_builds = 0

    def with_dc(self, **changes: object) -> Env:
        assert self.settings.jira_data_center is not None
        self.settings = replace(
            self.settings,
            jira_data_center=replace(self.settings.jira_data_center, **changes),  # type: ignore[arg-type]
        )
        return self

    def select(self, *project_keys: str) -> Env:
        self.store.mutate(
            lambda _current: JiraDataCenterState(site=DC_SITE, project_keys=project_keys)
        )
        return self

    def registry(self) -> TestDesignSourceRegistry:
        def factory(_base_url: str, _token: str) -> FakeIssueClient:
            self.client_builds += 1
            return self.client

        return composition_container.build_test_design_sources(
            self.settings,
            jira_dc_state_store=self.store,
            jira_dc_client_factory=factory,
        )

    def source(self) -> TestDesignSource:
        return self.registry().resolve("jira")

    def fetch(self, locator: str = "ENG-7") -> SourceDocument:
        return self.source().reader().fetch(SourceLocator("jira", locator))


@pytest.fixture
def env(tmp_path: Path) -> Env:
    return Env(tmp_path)


# Registration and readiness


def test_source_is_not_registered_when_data_center_mode_is_off(env: Env) -> None:
    env.settings = replace(env.settings, jira_data_center=None)

    with pytest.raises(TestDesignUnavailableError):
        env.registry().resolve("jira")


def test_mode_on_without_a_token_is_not_connected_and_never_calls_upstream(
    env: Env,
) -> None:
    env.with_dc(token=None)

    with pytest.raises(SourceNotConnectedError):
        env.source().reader()

    assert env.client_builds == 0
    assert env.client.calls == []


def test_mode_on_without_a_base_url_accepts_keys_but_not_urls(env: Env) -> None:
    env.with_dc(base_url=None)
    source = env.source()

    assert source.canonicalize("ENG-7") == "ENG-7"
    with pytest.raises(TestDesignValidationError):
        source.canonicalize("https://jira.example.com/jira/browse/ENG-7")
    with pytest.raises(SourceNotConnectedError):
        source.reader()


def test_rejected_token_requires_reauthorization_without_calling_upstream(
    env: Env,
) -> None:
    env.store.mutate(lambda _current: JiraDataCenterState(credentials_rejected=True))

    with pytest.raises(SourceReauthorizationRequiredError):
        env.source().reader()

    assert env.client.calls == []


# Locator security


@pytest.mark.parametrize(
    "locator",
    [
        "https://jira.example.com.attacker.com/jira/browse/ENG-7",
        "https://attacker.com/jira/browse/ENG-7",
        "https://jira.example.com@attacker.com/jira/browse/ENG-7",
        "https://user:pass@jira.example.com/jira/browse/ENG-7",
        "http://jira.example.com/jira/browse/ENG-7",
        "https://jira.example.com:8443/jira/browse/ENG-7",
        "https://jira.example.com/browse/ENG-7",
        "https://jira.example.com/jira-evil/browse/ENG-7",
        "https://jira.example.com/other/jira/browse/ENG-7",
        "https://jira.example.com/jira/../browse/ENG-7",
        "https://jira.example.com/jira/./browse/ENG-7",
        "https://jira.example.com/jira//browse/ENG-7",
        "https://jira.example.com/jira/browse/ENG%2D7",
        "https://jira.example.com/jira/browse/../ENG-7",
        "https://jira.example.com/jira/browse/ENG-7/",
        "https://jira.example.com/jira/browse/ENG-7/extra",
        "https://jira.example.com/jira/browse/ENG-7?focusedCommentId=1",
        "https://jira.example.com/jira/browse/ENG-7#comment",
        "https://jira.example.com/jira/projects/ENG/issues/ENG-7",
        "https://jira.exa\tmple.com/jira/browse/ENG-7",
        "ftp://jira.example.com/jira/browse/ENG-7",
        "ENG-07",
        "E-7",
        "ENG-0",
        "ENG 7",
    ],
)
def test_malformed_or_foreign_locators_are_rejected(env: Env, locator: str) -> None:
    with pytest.raises(TestDesignValidationError):
        env.source().canonicalize(locator)


@pytest.mark.parametrize(
    "locator",
    [
        "https://JIRA.EXAMPLE.COM/jira/browse/ENG-7",
        "https://jira.example.com./jira/browse/ENG-7",
        "https://jira.example.com:443/jira/browse/ENG-7",
        "https://jira.example.com/jira/browse/eng-7",
    ],
)
def test_equivalent_browse_urls_of_the_configured_instance_are_accepted(
    env: Env, locator: str
) -> None:
    assert env.source().canonicalize(locator) == "ENG-7"


# Canonicalization vs chat extraction


def test_canonicalize_accepts_any_valid_key_regardless_of_hub_selection(
    env: Env,
) -> None:
    assert env.source().canonicalize("OPS-3") == "OPS-3"
    env.select("ENG")
    assert env.source().canonicalize("OPS-3") == "OPS-3"


def test_extraction_only_takes_bare_keys_from_selected_projects(env: Env) -> None:
    env.select("ENG")
    source = env.source()

    assert source.extract_locator("Design tests for OPS-3") is None
    assert source.extract_locator("Design tests for ENG-7 please") == "ENG-7"
    assert source.extract_locator("Design tests for UTF-8 handling") is None


def test_without_a_saved_selection_no_bare_key_is_extracted(env: Env) -> None:
    assert env.source().extract_locator("Design tests for ENG-7") is None


def test_configured_browse_urls_are_extracted_regardless_of_selection(
    env: Env,
) -> None:
    env.select("ENG")

    assert (
        env.source().extract_locator(
            "Design tests for https://jira.example.com/jira/browse/OPS-3."
        )
        == "OPS-3"
    )


def test_canonicalize_touches_no_state_client_or_credentials(env: Env) -> None:
    class _ExplodingStore:
        def load(self) -> None:
            raise AssertionError("canonicalize must not read state")

        def mutate(self, _mutator: object) -> None:
            raise AssertionError("canonicalize must not write state")

    reads = 0
    dc = env.settings.jira_data_center

    def provider():  # noqa: ANN202
        nonlocal reads
        reads += 1
        return dc

    source = composition_container.build_test_design_sources(
        env.settings,
        jira_dc_state_store=_ExplodingStore(),
        jira_dc_client_factory=lambda *_: pytest.fail("no client in canonicalize"),
        jira_dc_settings_provider=provider,
    ).resolve("jira")
    reads_after_build = reads

    assert source.canonicalize("eng-7") == "ENG-7"
    assert source.canonicalize("https://jira.example.com/jira/browse/ENG-7") == "ENG-7"
    assert reads == reads_after_build


# Evidence model


def test_evidence_orders_summary_description_then_acceptance_criteria(env: Env) -> None:
    document = env.fetch()

    assert document.content == (
        "# ENG-7: Login\n\n"
        "## Description\n\nUsers log in with **email**.\n\n"
        "## Acceptance criteria\n\nLockout after 5 attempts."
    )
    assert document.reference.source_id == "issue:10001"
    assert document.reference.source_type == "jira"
    assert document.metadata.title == "ENG-7: Login"
    assert document.metadata.extra["revision"] == "2026-09-14T12:00:00.000+0000"
    assert env.client.calls == [
        ("ENG-7", ("summary", "description", "updated", AC_FIELD))
    ]


def test_unset_acceptance_criteria_field_is_not_requested(env: Env) -> None:
    env.with_dc(acceptance_criteria_field=None)

    document = env.fetch()

    assert "Acceptance criteria" not in document.content
    assert env.client.calls == [("ENG-7", ("summary", "description", "updated"))]


def test_missing_description_still_uses_acceptance_criteria(env: Env) -> None:
    env.client.fields["description"] = None

    document = env.fetch()

    assert document.content == (
        "# ENG-7: Login\n\n## Acceptance criteria\n\nLockout after 5 attempts."
    )


@pytest.mark.parametrize(
    "value",
    [None, {"value": PAYLOAD_SENTINEL}, [PAYLOAD_SENTINEL], 42],
    ids=["null", "select-option", "list", "number"],
)
def test_absent_or_non_text_acceptance_criteria_are_omitted(
    env: Env, value: object
) -> None:
    env.client.fields[AC_FIELD] = value

    document = env.fetch()

    assert "Acceptance criteria" not in document.content
    assert PAYLOAD_SENTINEL not in repr(document)


def test_missing_acceptance_criteria_field_is_omitted(env: Env) -> None:
    del env.client.fields[AC_FIELD]

    assert "Acceptance criteria" not in env.fetch().content


def test_summary_alone_is_insufficient_evidence(env: Env) -> None:
    env.client.fields["description"] = "   "
    env.client.fields[AC_FIELD] = None

    with pytest.raises(InsufficientEvidenceError):
        env.fetch()


@pytest.mark.parametrize(
    "arrange",
    [
        lambda c: c.fields.__setitem__("summary", "  "),
        lambda c: c.fields.__setitem__("description", {"type": "doc"}),
        lambda c: setattr(c, "issue_id", "ENG-7"),
        lambda c: setattr(c, "key", "OPS-9"),
    ],
    ids=["blank-summary", "non-text-description", "non-digit-id", "moved-key"],
)
def test_malformed_or_mismatched_issue_is_a_validation_error(
    env: Env, arrange
) -> None:
    arrange(env.client)

    with pytest.raises(TestDesignValidationError):
        env.fetch()


def test_revision_only_change_keeps_confirm_succeeding(
    env: Env, tmp_path: Path
) -> None:
    facade = build_fake_facade(tmp_path, sources=env.registry())
    draft = facade.create_draft(
        CreateTestDesignDraftRequest(
            conversation_id="conv-jira",
            source_locator=SourceLocatorView(provider="jira", locator="ENG-7"),
        )
    )
    patched = facade.patch_draft(
        draft.draft_id,
        PatchTestDesignDraftRequest(
            expected_version=draft.version,
            candidates=tuple(
                replace(item, selected=index == 0)
                for index, item in enumerate(draft.candidates)
            ),
        ),
    )
    env.client.fields["updated"] = "2026-09-15T08:00:00.000+0000"

    confirmed = facade.confirm_draft(patched.draft_id, expected_version=patched.version)

    assert confirmed.status == "ready"


# Transport failures stay neutral


@pytest.mark.parametrize(
    ("raised", "expected"),
    [
        (JiraRateLimitError(30), ConnectorRateLimitError),
        (ConnectorTimeoutError("The Jira request timed out."), ConnectorTimeoutError),
        (ConnectorNetworkError("The Jira network request failed."), ConnectorNetworkError),
        (JiraPaginationError(), ConnectorUnavailableError),
        (ConnectorUnavailableError("Jira is temporarily unavailable."), ConnectorUnavailableError),
        (ConnectorError("The Jira request failed."), ConnectorError),
    ],
)
def test_transport_failures_surface_as_neutral_base_errors_without_a_cause(
    env: Env, raised: Exception, expected: type[Exception]
) -> None:
    env.client.error = raised

    with pytest.raises(expected) as caught:
        env.fetch()

    assert type(caught.value) is expected
    assert "jira" not in str(caught.value).casefold()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert caught.value.__suppress_context__ is True
