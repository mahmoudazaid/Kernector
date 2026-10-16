"""Jira Cloud Test Design source: locators, grant readiness, evidence, refresh."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from application.errors import (
    InsufficientEvidenceError,
    SourceItemNotFoundError,
    SourceNotConnectedError,
    SourceReauthorizationRequiredError,
)
from composition import container as composition_container
from composition.test_design.errors import TestDesignEvidenceChangedError, TestDesignValidationError
from composition.test_design.facade import (
    CreateTestDesignDraftRequest,
    GenerateTestDesignCasesRequest,
    PatchTestDesignDraftRequest,
    SourceLocatorView,
)
from composition.test_design.sources import AmbiguousSourceLocatorError
from domain.errors import (
    ConnectorAuthError,
    ConnectorError,
    ConnectorNotFoundError,
    ConnectorRateLimitError,
    ConnectorTimeoutError,
)
from domain.knowledge import SourceLocator
from infrastructure.config import Settings, load_settings
from infrastructure.connectors.jira.errors import JiraRateLimitError
from infrastructure.connectors.jira.oauth import (
    JiraOAuthConnectionStore,
    JiraOAuthError,
    JiraOAuthInvalidGrantError,
)
from packs.software_delivery.test_design.limits import MAX_EVIDENCE_TEXT_CHARS
from packs.software_delivery.test_design.suggest_tests import TRUNCATION_MARKER
from test.composition.jira.jira_fakes import (
    ACME,
    BETA,
    SECRET,
    FakeGateway,
    connection,
    jira_settings,
    stores,
)
from test.composition.test_design.test_design_fakes import build_fake_facade

AC_FIELD = "customfield_10200"
BROWSE = "https://acme.atlassian.net/browse/FD-2"
_ADF = {
    "type": "doc",
    "content": [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Users log in with email."}],
        }
    ],
}


class _MemoryStore:
    """Grant object the file codec cannot represent (token missing, flag false)."""

    def __init__(self, current: object) -> None:
        self.current = current

    def load(self) -> object:
        return self.current


class _UnlinkOnArmedLoad(JiraOAuthConnectionStore):
    """Drop the grant file after the next load, before refresh re-reads it."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.armed = False

    def load(self):  # noqa: ANN201
        value = super().load()
        if self.armed:
            self._path.unlink(missing_ok=True)
            self.armed = False
        return value


class Script:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.rejected: set[str] = set()
        self.error: Exception | None = None
        self.fields: dict[str, object] = {
            "summary": "Login",
            "description": _ADF,
            "updated": "2026-09-14T12:00:00.000+0000",
            AC_FIELD: "Lockout after 5 attempts.",
        }
        self.issue_id = "10001"
        self.key: str | None = None
        self.on_call = None

    def factory(self, token: str, _cloud_id: str) -> object:
        script = self

        class _Client:
            def get_issue(self, key: str, fields: Sequence[str]) -> Mapping[str, object]:
                script.calls.append((token, key))
                if script.on_call is not None:
                    script.on_call(token)
                if token in script.rejected:
                    raise ConnectorAuthError("rejected")
                if script.error is not None:
                    raise script.error
                return {
                    "id": script.issue_id,
                    "key": script.key or key,
                    "fields": {
                        name: value
                        for name, value in script.fields.items()
                        if name in fields
                    },
                }

        return _Client()


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.script = Script()
        self.gateway = FakeGateway()
        self.settings: Settings = replace(
            jira_settings(
                load_settings(), tmp_path, acceptance_criteria_field=AC_FIELD
            ),
            jira_data_center=None,
        )
        _, self.store = stores(self.settings)
        self.store.save(connection(project_keys=("FD",), site=ACME))

    def source_registry(self, *, store=None):
        return composition_container.build_test_design_sources(
            self.settings,
            jira_cloud_connection_store=self.store if store is None else store,
            jira_cloud_gateway=self.gateway,
            jira_cloud_client_factory=self.script.factory,
        )

    def source(self, *, store=None):
        return self.source_registry(store=store).resolve("jira")

    def fetch(self, locator: str = "FD-2"):
        return self.source().reader().fetch(SourceLocator("jira", locator))


def _links_are_clear(error: BaseException) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None


def test_canonicalize_accepts_key_and_saved_site_url_without_project_selection(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path)
    source = env.source()

    assert source.canonicalize("FD-2") == "FD-2"
    assert source.canonicalize(" fd-2 ") == "FD-2"
    assert source.canonicalize(BROWSE) == "FD-2"
    assert source.canonicalize("https://acme.atlassian.net/browse/OPS-9") == "OPS-9"


@pytest.mark.parametrize(
    "locator",
    ["https://other.atlassian.net/browse/FD-2", "acme/app#7", "7"],
)
def test_canonicalize_rejects_foreign_hosts_and_non_keys(
    tmp_path: Path, locator: str
) -> None:
    with pytest.raises(TestDesignValidationError):
        Env(tmp_path).source().canonicalize(locator)


def test_canonicalize_without_a_site_keeps_bare_keys_and_rejects_urls(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path)
    env.store.save(connection(project_keys=("FD",), site=None))
    source = env.source()

    assert source.canonicalize("fd-2") == "FD-2"
    with pytest.raises(TestDesignValidationError):
        source.canonicalize(BROWSE)


def test_extract_locator_uses_selection_for_keys_and_site_for_urls(
    tmp_path: Path,
) -> None:
    source = Env(tmp_path).source()

    assert source.extract_locator("design tests FD-2") == "FD-2"
    assert source.extract_locator("design tests OPS-9") is None
    assert (
        source.extract_locator("design tests https://acme.atlassian.net/browse/OPS-9")
        == "OPS-9"
    )
    assert (
        source.extract_locator("design tests https://other.atlassian.net/browse/FD-2")
        is None
    )
    with pytest.raises(AmbiguousSourceLocatorError):
        source.extract_locator("design tests FD-2 and FD-3")


def test_saved_site_and_projects_apply_without_rebuilding_the_source(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path)
    source = env.source()
    assert source.extract_locator("design tests OPS-9") is None

    env.store.save(connection(project_keys=("OPS",), site=BETA))

    assert source.extract_locator("design tests OPS-9") == "OPS-9"
    assert source.canonicalize("https://beta.atlassian.net/browse/OPS-9") == "OPS-9"
    with pytest.raises(TestDesignValidationError):
        source.canonicalize(BROWSE)


def test_reader_precedence_for_incomplete_and_reauth_grants(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.store.clear()
    with pytest.raises(SourceNotConnectedError) as missing:
        env.source().reader()
    _links_are_clear(missing.value)
    assert env.script.calls == []

    env.store.save(
        connection(
            access_token=None,
            refresh_token=None,
            reauthorization_required=True,
            site=None,
        )
    )
    with pytest.raises(SourceReauthorizationRequiredError) as rejected:
        env.source().reader()
    _links_are_clear(rejected.value)

    memory = _MemoryStore(
        connection(access_token=None, reauthorization_required=False, site=ACME)
    )
    with pytest.raises(SourceReauthorizationRequiredError):
        env.source(store=memory).reader()

    env.store.save(connection(access_token=f"{SECRET}-access-0", site=None))
    with pytest.raises(SourceNotConnectedError):
        env.source().reader()


def test_fetch_renders_adf_description_plain_and_adf_acceptance_criteria(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path)
    document = env.fetch()

    assert document.content == (
        "# FD-2: Login\n\n"
        "## Description\n\n"
        "Users log in with email.\n\n"
        "## Acceptance criteria\n\n"
        "Lockout after 5 attempts."
    )
    assert document.metadata.extra["revision"] == "2026-09-14T12:00:00.000+0000"
    env.script.fields[AC_FIELD] = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Lock after 5."}]}
        ],
    }
    assert "Lock after 5." in env.fetch().content


def test_empty_rendered_evidence_is_insufficient(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.script.fields["description"] = None
    env.script.fields[AC_FIELD] = "  "

    with pytest.raises(InsufficientEvidenceError):
        env.fetch()


def test_malformed_payload_is_a_validation_error_without_a_cause(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.script.key = "OPS-9"

    with pytest.raises(TestDesignValidationError) as caught:
        env.fetch()

    _links_are_clear(caught.value)
    assert caught.value.__suppress_context__ is True


def test_oversized_acceptance_criteria_is_inside_the_document_budget(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path)
    env.script.fields["description"] = "short"
    env.script.fields[AC_FIELD] = "a" * 20_000

    content = env.fetch().content

    assert content.startswith("# FD-2: Login")
    assert "short" in content
    assert content.endswith(TRUNCATION_MARKER)
    assert len(content) <= MAX_EVIDENCE_TEXT_CHARS


def test_combined_oversized_fields_stay_inside_the_document_budget(
    tmp_path: Path,
) -> None:
    env = Env(tmp_path)
    env.script.fields["description"] = "d" * 20_000
    env.script.fields[AC_FIELD] = "a" * 20_000

    content = env.fetch().content

    assert content.startswith("# FD-2: Login")
    assert content.endswith(TRUNCATION_MARKER)
    assert len(content) <= MAX_EVIDENCE_TEXT_CHARS


def test_expired_access_token_is_refreshed_before_fetch(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.store.save(connection(project_keys=("FD",), access_token_expires_at=0.0))

    document = env.fetch()

    assert document.content.startswith("# FD-2: Login")
    assert env.gateway.refresh_calls == [f"{SECRET}-refresh-0"]
    assert env.script.calls[0][0] == f"{SECRET}-access-1"
    stored = env.store.load()
    assert stored is not None
    assert stored.access_token == f"{SECRET}-access-1"
    assert stored.refresh_token == f"{SECRET}-refresh-1"
    assert stored.reauthorization_required is False


def test_rejected_access_token_refreshes_and_retries(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.script.rejected.add(f"{SECRET}-access-0")
    seen: list[str | None] = []

    def _on_call(_token: str) -> None:
        stored = env.store.load()
        seen.append(None if stored is None else stored.refresh_token)

    env.script.on_call = _on_call

    env.fetch()

    assert [token for token, _key in env.script.calls] == [
        f"{SECRET}-access-0",
        f"{SECRET}-access-1",
    ]
    assert seen == [f"{SECRET}-refresh-0", f"{SECRET}-refresh-1"]
    stored = env.store.load()
    assert stored is not None
    assert stored.reauthorization_required is False


def test_invalid_grant_requires_reauth_and_does_not_fetch(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.store.save(connection(project_keys=("FD",), access_token_expires_at=0.0))
    env.gateway.refresh_results.append(JiraOAuthInvalidGrantError("rejected"))

    with pytest.raises(SourceReauthorizationRequiredError) as caught:
        env.fetch()

    _links_are_clear(caught.value)
    assert caught.value.__suppress_context__ is True
    assert env.script.calls == []
    stored = env.store.load()
    assert stored is not None
    assert stored.reauthorization_required is True
    assert stored.access_token is None
    assert stored.refresh_token is None


def test_missing_refresh_token_requires_reauth_without_a_fetch(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.store.save(
        connection(
            project_keys=("FD",),
            access_token_expires_at=0.0,
            refresh_token=None,
        )
    )

    with pytest.raises(SourceReauthorizationRequiredError):
        env.fetch()

    assert env.gateway.refresh_calls == []
    assert env.script.calls == []


def test_retry_still_rejected_requires_reauth(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.script.rejected.update({f"{SECRET}-access-0", f"{SECRET}-access-1"})

    with pytest.raises(SourceReauthorizationRequiredError) as caught:
        env.fetch()

    _links_are_clear(caught.value)
    stored = env.store.load()
    assert stored is not None
    assert stored.reauthorization_required is True


def test_transient_refresh_failure_is_a_neutral_request_error(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.store.save(connection(project_keys=("FD",), access_token_expires_at=0.0))
    env.gateway.refresh_results.append(JiraOAuthError("down"))

    with pytest.raises(ConnectorError) as caught:
        env.fetch()

    assert type(caught.value) is ConnectorError
    assert str(caught.value) == "The source request failed."
    _links_are_clear(caught.value)
    assert caught.value.__suppress_context__ is True
    stored = env.store.load()
    assert stored is not None
    assert stored.refresh_token == f"{SECRET}-refresh-0"
    assert stored.reauthorization_required is False


def test_grant_deleted_during_refresh_is_not_connected(tmp_path: Path) -> None:
    env = Env(tmp_path)
    store = _UnlinkOnArmedLoad(env.settings.jira_oauth.token_path)
    store.save(connection(project_keys=("FD",), access_token_expires_at=0.0))
    source = env.source(store=store)
    reader = source.reader()
    store.armed = True

    with pytest.raises(SourceNotConnectedError) as caught:
        reader.fetch(SourceLocator("jira", "FD-2"))

    _links_are_clear(caught.value)
    assert env.script.calls == []


@pytest.mark.parametrize(
    ("raised", "expected", "message"),
    [
        (ConnectorNotFoundError("missing"), SourceItemNotFoundError, "not found"),
        (JiraRateLimitError(30), ConnectorRateLimitError, "rate limit"),
        (ConnectorTimeoutError("slow"), ConnectorTimeoutError, "timed out"),
    ],
)
def test_fetch_transport_errors_are_neutral(
    tmp_path: Path, raised: Exception, expected: type[Exception], message: str
) -> None:
    env = Env(tmp_path)
    env.script.error = raised

    with pytest.raises(expected) as caught:
        env.fetch()

    assert type(caught.value) is expected
    assert message in str(caught.value)
    _links_are_clear(caught.value)
    assert caught.value.__suppress_context__ is True


def test_acceptance_criteria_only_change_is_evidence_changed(tmp_path: Path) -> None:
    env = Env(tmp_path)
    facade = build_fake_facade(tmp_path, sources=env.source_registry())
    draft = facade.create_draft(
        CreateTestDesignDraftRequest(
            conversation_id="conv-cloud",
            source_locator=SourceLocatorView(provider="jira", locator="FD-2"),
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
    confirmed = facade.confirm_draft(patched.draft_id, expected_version=patched.version)
    env.script.fields[AC_FIELD] = "Lockout after 9 attempts."

    with pytest.raises(TestDesignEvidenceChangedError):
        facade.generate_cases(
            confirmed.draft_id,
            GenerateTestDesignCasesRequest(expected_version=confirmed.version),
        )

    assert facade.get_draft(confirmed.draft_id).generated_cases == ()


def test_revision_only_change_does_not_block_generate(tmp_path: Path) -> None:
    env = Env(tmp_path)
    facade = build_fake_facade(tmp_path, sources=env.source_registry())
    draft = facade.create_draft(
        CreateTestDesignDraftRequest(
            conversation_id="conv-cloud",
            source_locator=SourceLocatorView(provider="jira", locator="FD-2"),
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
    confirmed = facade.confirm_draft(patched.draft_id, expected_version=patched.version)
    env.script.fields["updated"] = "2026-09-15T08:00:00.000+0000"

    generated = facade.generate_cases(
        confirmed.draft_id,
        GenerateTestDesignCasesRequest(expected_version=confirmed.version),
    )

    assert generated.generated_cases
    assert env.fetch().metadata.extra["revision"] == "2026-09-15T08:00:00.000+0000"


def test_cloud_oauth_registers_jira_and_data_center_wins(tmp_path: Path) -> None:
    env = Env(tmp_path)
    assert env.source_registry().providers == ("github", "jira")

    from test.composition.jira.jira_fakes import dc_settings

    dc = dc_settings(env.settings, tmp_path)
    providers = composition_container.build_test_design_sources(dc).providers
    assert providers == ("github", "jira")
    assert (
        type(composition_container.build_test_design_sources(dc).resolve("jira")).__name__
        == "JiraDataCenterTestDesignSource"
    )

    neither = replace(
        env.settings,
        jira_oauth=replace(
            env.settings.jira_oauth, client_id=None, client_secret=None, redirect_uri=None
        ),
    )
    assert composition_container.build_test_design_sources(neither).providers == ("github",)
