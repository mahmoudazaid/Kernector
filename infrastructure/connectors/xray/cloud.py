"""Xray Cloud importer (GraphQL API v2, client-credentials authentication).

Discovery reads the project's test types (``getProjectSettings``); a manual
test needs a ``Steps`` kind and a Cucumber test a ``Gherkin`` kind. Cloud API
keys cannot read Jira link metadata, so link support follows the configured
link type name. The client secret and bearer token are sent only to the
configured base URL; redirects are never followed.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from domain.errors import ConnectorAuthError, ConnectorError, ConnectorUnavailableError
from domain.test_management.xray import (
    IssueLookupResult,
    JiraIssueSummary,
    StoryNamingContext,
    XrayCreateWarning,
    XrayImportResult,
    JIRA_PATCH_FIELDS,
    XrayTestCreateSchema,
    XrayTestDetails,
    XrayTestDetailsResult,
    XrayTestPatch,
    XrayTestSpec,
    XrayUpdateCapabilities,
    XrayUpdateNotConfirmedError,
    XrayUpdateRejectedError,
    XrayUpdateUncertainError,
)
from infrastructure.connectors.xray.batch import create_each
from infrastructure.connectors.xray.errors import (
    MSG_AUTH,
    MSG_REQUEST_FAILED,
    MSG_UNAVAILABLE,
    XrayRejectedError,
    XraySchemaError,
    diagnostic,
    map_http_error,
)
from infrastructure.connectors.xray.cloud_update import (
    DETAILS_SELECTION,
    Mutation,
    mutations,
    parse_test,
)
from infrastructure.connectors.xray.details import confirms_definition
from infrastructure.connectors.xray.jql import jql_string
from infrastructure.connectors.xray.schema import SchemaKey, XraySchemaCache

if TYPE_CHECKING:
    import httpx

_PROJECT_SETTINGS_QUERY = (
    "query($projectKey: String) { getProjectSettings(projectIdOrKey: $projectKey) "
    "{ testTypeSettings { testTypes { id name kind } } } }"
)
_CREATE_TEST_MUTATION = (
    "mutation($testType: UpdateTestTypeInput, $steps: [CreateStepInput], "
    "$gherkin: String, $jira: JSON!) { createTest(testType: $testType, steps: $steps, "
    "gherkin: $gherkin, jira: $jira) { test { issueId scenarioType "
    'jira(fields: ["key"]) } warnings } }'
)
_SEARCH_SELECTION = (
    '{ total start limit results { jira(fields: ["key", "summary", "issuetype"]) } }'
)
_NAMING_SELECTION = (
    '{ total start limit results { jira(fields: ["key", "summary", "issuetype", "parent"]) } }'
)
_GET_TESTS = "getTests"
_GET_COVERABLE = "getCoverableIssues"
_JIRA_PROJECT = re.compile(r"[A-Z][A-Z0-9_]*")


def _search_query(name: str, selection: str) -> str:
    return (
        "query($jql: String, $start: Int, $limit: Int!) { "
        f"{name}(jql: $jql, start: $start, limit: $limit) {selection} }}"
    )


_SEARCH_QUERIES = {name: _search_query(name, _SEARCH_SELECTION) for name in (_GET_TESTS, _GET_COVERABLE)}
_ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]*-[1-9][0-9]*")
_OUTLINE_TYPES = frozenset({"scenario_outline", "scenario outline"})
_PAGE_LIMIT = 100
_MAX_PAGES = 20
_KEY_CHUNK = 50
_MAX_CHUNK_SPLITS = 50


class _UnauthorizedError(ConnectorAuthError):
    """Xray answered HTTP 401; a cached bearer token may have expired."""

    def __init__(self) -> None:
        super().__init__(MSG_AUTH)


class _SearchRefusedError(Exception):
    """A search answered with GraphQL ``errors``; never treated as an empty result."""


@dataclass(frozen=True, slots=True)
class CloudTestTypes:
    """Discovered Xray Cloud test type ids; ``None`` when the kind is missing."""

    manual_id: str | None
    cucumber_id: str | None


class XrayCloudImporter:
    """:class:`domain.ports.XrayTestImporter` and :class:`domain.ports.XrayIssueLookup`
    for Xray Cloud.

    Lookups go through Xray JQL searches, so a key is never reported missing:
    a key neither search returns stays unresolved. Searches are chunked and
    paged within fixed bounds; an incomplete search raises. A chunk refused
    with GraphQL errors is bisected within a fixed split budget; keys left in
    refused chunks stay unresolved.
    """

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        project_key: str,
        link_type: str,
        cache: XraySchemaCache,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        import httpx

        self._httpx = httpx
        self._base_url = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._project_key = project_key
        self._link_type = link_type.strip()
        self._cache = cache
        self._token: str | None = None
        self._client = httpx.Client(
            base_url=f"{self._base_url}/api/v2",
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "kernector-xray-connector"},
        )

    def __repr__(self) -> str:
        return (
            f"XrayCloudImporter(base_url={self._base_url!r}, "
            f"project_key={self._project_key!r}, client_secret='***')"
        )

    @property
    def _schema_key(self) -> SchemaKey:
        return ("cloud", self._base_url, self._project_key)

    def schema(self) -> XrayTestCreateSchema:
        types, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        return XrayTestCreateSchema(
            project_key=self._project_key,
            supports_manual=types.manual_id is not None,
            supports_cucumber=types.cucumber_id is not None,
            supports_issue_link=bool(self._link_type),
            supports_cucumber_outline=types.cucumber_id is not None,
        )

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        types, from_cache = self._cache.get_or_discover(self._schema_key, self._discover)
        warnings: list[XrayCreateWarning] = []

        def create(spec: XrayTestSpec, current: CloudTestTypes) -> str:
            return self._create(spec, current, warnings)

        result = create_each(
            specs,
            mapping=types,
            from_cache=from_cache,
            rediscover=self._rediscover,
            create=create,
        )
        return replace(result, warnings=tuple(warnings))

    def find_issues(self, keys: Sequence[str]) -> IssueLookupResult:
        """Resolve keys through ``getTests`` and ``getCoverableIssues``; never reports missing."""
        valid = [key for key in dict.fromkeys(keys) if _ISSUE_KEY.fullmatch(key)]
        found: dict[str, JiraIssueSummary] = {}
        pending = [valid[index : index + _KEY_CHUNK] for index in range(0, len(valid), _KEY_CHUNK)]
        pending.reverse()
        splits = 0
        while pending:
            chunk = pending.pop()
            try:
                found.update(self._resolve(chunk))
            except _SearchRefusedError:
                if len(chunk) > 1 and splits < _MAX_CHUNK_SPLITS:
                    splits += 1
                    half = len(chunk) // 2
                    pending.extend((chunk[half:], chunk[:half]))
        return IssueLookupResult(found=found, missing=frozenset())

    def linked_tests(self, story_key: str) -> tuple[JiraIssueSummary, ...]:
        """Every test linked to ``story_key``; GraphQL errors or incomplete paging raise."""
        if not _ISSUE_KEY.fullmatch(story_key):
            raise ConnectorError(MSG_REQUEST_FAILED)
        try:
            items = self._search(_GET_TESTS, f'issue in linkedIssues("{story_key}")')
        except _SearchRefusedError:
            raise ConnectorError(MSG_REQUEST_FAILED) from None
        return tuple(_issue_summary(item, is_test=True) for item in items)

    def list_tests(
        self, project_key: str, *, component: str | None = None
    ) -> tuple[JiraIssueSummary, ...]:
        """Every Test in ``project_key``, optionally filtered by component name."""
        if not project_key or not _JIRA_PROJECT.fullmatch(project_key):
            raise ConnectorError(MSG_REQUEST_FAILED)
        clauses = [f'project = "{project_key}"']
        if component is not None:
            if not component.strip():
                raise ConnectorError(MSG_REQUEST_FAILED)
            clauses.append(f"component = {jql_string(component.strip())}")
        try:
            items = self._search(_GET_TESTS, " AND ".join(clauses))
        except _SearchRefusedError:
            raise ConnectorError(MSG_REQUEST_FAILED) from None
        by_key: dict[str, JiraIssueSummary] = {}
        for item in items:
            summary = _issue_summary(item, is_test=True)
            by_key.setdefault(summary.key, summary)
        return tuple(by_key.values())

    def story_naming_context(self, story_key: str) -> StoryNamingContext:
        """Coverable-issue summary plus ``parent`` epic when GraphQL returns it."""
        if not _ISSUE_KEY.fullmatch(story_key):
            raise ConnectorError(MSG_REQUEST_FAILED)
        try:
            items = self._search(
                _GET_COVERABLE,
                f'key = "{story_key}"',
                selection=_NAMING_SELECTION,
            )
        except _SearchRefusedError:
            raise ConnectorError(MSG_REQUEST_FAILED) from None
        if len(items) != 1:
            raise ConnectorError(MSG_REQUEST_FAILED)
        return _naming_context(items[0], story_key)

    def capabilities(self) -> XrayUpdateCapabilities:
        """Xray-only credentials cannot change Jira fields (summary, components, links)."""
        return XrayUpdateCapabilities(jira_fields=False, story_link_type=bool(self._link_type))

    def test_details(self, keys: Sequence[str]) -> XrayTestDetailsResult:
        """Read tests through chunked, paged ``getTests``; any incomplete read raises."""
        valid = [key for key in dict.fromkeys(keys) if _ISSUE_KEY.fullmatch(key)]
        if not valid:
            return XrayTestDetailsResult()
        types, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        type_switch = types.manual_id is not None and types.cucumber_id is not None
        found: dict[str, XrayTestDetails] = {}
        unreadable: set[str] = set()
        seen: set[str] = set()
        for index in range(0, len(valid), _KEY_CHUNK):
            chunk = valid[index : index + _KEY_CHUNK]
            try:
                items = self._search(
                    _GET_TESTS, f"key in ({', '.join(chunk)})", selection=DETAILS_SELECTION
                )
            except _SearchRefusedError:
                raise ConnectorError(MSG_REQUEST_FAILED) from None
            for item in items:
                key, details = parse_test(item, type_switch=type_switch)
                if key in seen:
                    raise ConnectorError(MSG_REQUEST_FAILED)
                seen.add(key)
                if key not in chunk:
                    continue
                if details is None:
                    unreadable.add(key)
                else:
                    found[key] = details
        return XrayTestDetailsResult(found=found, unreadable=frozenset(unreadable))

    def update_test(self, patch: XrayTestPatch) -> None:
        """Run the definition mutations in their verified order, then read back type changes."""
        if JIRA_PATCH_FIELDS & set(patch.changed):
            raise XrayUpdateRejectedError()
        manual_id = cucumber_id = None
        if patch.kind_change is not None:
            types, _ = self._cache.get_or_discover(self._schema_key, self._discover)
            manual_id, cucumber_id = types.manual_id, types.cucumber_id
        plan = mutations(patch, manual_id=manual_id, cucumber_id=cucumber_id)
        if plan is None:
            raise XrayUpdateRejectedError()
        for index, mutation in enumerate(plan):
            self._mutate(mutation, patch.issue_id, partial=index > 0)
        if patch.kind_change is not None or patch.scenario_type_change is not None:
            self._confirm(patch)

    def _mutate(self, mutation: Mutation, issue_id: str, *, partial: bool) -> None:
        failure: ConnectorError | None = None
        try:
            payload = self._graphql_payload(mutation.query, mutation.variables)
        except ConnectorError as error:
            failure = _write_failure(error, partial=partial)
        if failure is not None:
            raise failure from None
        data = payload.get("data")
        result = data.get(mutation.name) if isinstance(data, Mapping) else None
        if payload.get("errors") and result is None and not partial:
            raise XrayUpdateRejectedError()
        if payload.get("errors") or not mutation.succeeded(result, issue_id):
            raise XrayUpdateUncertainError(partial=partial)

    def _confirm(self, patch: XrayTestPatch) -> None:
        try:
            details = self.test_details([patch.key]).found.get(patch.key)
        except ConnectorError:
            details = None
        if details is None or not confirms_definition(patch, details):
            raise XrayUpdateNotConfirmedError()

    def _resolve(self, keys: Sequence[str]) -> dict[str, JiraIssueSummary]:
        jql = f"key in ({', '.join(keys)})"
        wanted = set(keys)
        found: dict[str, JiraIssueSummary] = {}
        for item in self._search(_GET_TESTS, jql):
            summary = _issue_summary(item, is_test=True)
            if summary.key in wanted:
                found[summary.key] = summary
        for item in self._search(_GET_COVERABLE, jql):
            summary = _issue_summary(item, is_test=False)
            if summary.key in wanted and summary.key not in found:
                found[summary.key] = summary
        return found

    def _search(self, name: str, jql: str, *, selection: str | None = None) -> list[object]:
        query = _SEARCH_QUERIES[name] if selection is None else _search_query(name, selection)
        items: list[object] = []
        seen_keys: set[str] = set()
        for _ in range(_MAX_PAGES):
            start = len(items)
            variables = {"jql": jql, "start": start, "limit": _PAGE_LIMIT}
            payload = self._graphql_payload(query, variables)
            if payload.get("errors"):
                raise _SearchRefusedError()
            data = payload.get("data")
            page = data.get(name) if isinstance(data, Mapping) else None
            total = page.get("total") if isinstance(page, Mapping) else None
            results = page.get("results") if isinstance(page, Mapping) else None
            if not isinstance(results, list) or not isinstance(total, int) or isinstance(
                total, bool
            ):
                raise ConnectorError(MSG_REQUEST_FAILED)
            if not results:
                if start >= total:
                    return items
                raise ConnectorError(MSG_REQUEST_FAILED)
            page_keys = [_result_key(item) for item in results]
            if any(key in seen_keys for key in page_keys):
                raise ConnectorUnavailableError(MSG_UNAVAILABLE)
            seen_keys.update(page_keys)
            items.extend(results)
            if len(items) >= total:
                return items
            if len(results) == 0:
                raise ConnectorError(MSG_REQUEST_FAILED)
        raise ConnectorUnavailableError(MSG_UNAVAILABLE)

    def _rediscover(self) -> CloudTestTypes:
        self._cache.invalidate(self._schema_key)
        types, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        return types

    def _create(
        self, spec: XrayTestSpec, types: CloudTestTypes, warnings: list[XrayCreateWarning]
    ) -> str:
        type_id = types.manual_id if spec.kind == "manual" else types.cucumber_id
        if type_id is None or (spec.link_issue_key and not self._link_type):
            raise XrayRejectedError()
        payload = self._graphql_payload(_CREATE_TEST_MUTATION, self._create_variables(spec, type_id))
        if payload.get("errors"):
            raise XrayRejectedError()
        data = payload.get("data")
        created = data.get("createTest") if isinstance(data, Mapping) else None
        test = created.get("test") if isinstance(created, Mapping) else None
        jira = test.get("jira") if isinstance(test, Mapping) else None
        key = jira.get("key") if isinstance(jira, Mapping) else None
        if not isinstance(key, str) or not key:
            raise ConnectorError(MSG_REQUEST_FAILED)
        assert isinstance(created, Mapping) and isinstance(test, Mapping)
        if spec.link_issue_key and created.get("warnings"):
            warnings.append(XrayCreateWarning(key, "link_not_confirmed"))
        elif spec.kind == "cucumber" and spec.outline:
            scenario_type = test.get("scenarioType")
            if not isinstance(scenario_type, str) or scenario_type.casefold() not in _OUTLINE_TYPES:
                warnings.append(XrayCreateWarning(key, "outline_not_confirmed"))
        return key

    def _create_variables(self, spec: XrayTestSpec, type_id: str) -> dict[str, object]:
        fields: dict[str, object] = {"summary": spec.title, "project": {"key": self._project_key}}
        if spec.preconditions:
            fields["description"] = spec.preconditions
        if spec.component:
            fields["components"] = [{"name": spec.component}]
        jira: dict[str, object] = {"fields": fields}
        if spec.link_issue_key:
            jira["update"] = {
                "issuelinks": [
                    {
                        "add": {
                            "type": {"name": self._link_type},
                            "outwardIssue": {"key": spec.link_issue_key},
                        }
                    }
                ]
            }
        variables: dict[str, object] = {"testType": {"id": type_id}}
        if spec.kind == "manual":
            variables["steps"] = [
                {"action": step.action, "data": "", "result": step.expected} for step in spec.steps
            ]
        else:
            variables["gherkin"] = spec.gherkin
        variables["jira"] = jira
        return variables

    def _discover(self) -> CloudTestTypes:
        data = self._graphql(_PROJECT_SETTINGS_QUERY, {"projectKey": self._project_key})
        settings = data.get("getProjectSettings")
        type_settings = settings.get("testTypeSettings") if isinstance(settings, Mapping) else None
        raw_types = type_settings.get("testTypes") if isinstance(type_settings, Mapping) else None
        if not isinstance(raw_types, list):
            raise XraySchemaError()
        test_types = [t for t in raw_types if isinstance(t, Mapping)]
        return CloudTestTypes(
            manual_id=_pick_type(test_types, kind="Steps", preferred="Manual"),
            cucumber_id=_pick_type(test_types, kind="Gherkin", preferred="Cucumber"),
        )

    def _graphql(self, query: str, variables: Mapping[str, object]) -> Mapping[str, object]:
        data = self._graphql_payload(query, variables).get("data")
        if not isinstance(data, Mapping):
            raise ConnectorError(MSG_REQUEST_FAILED)
        return data

    def _graphql_payload(
        self, query: str, variables: Mapping[str, object]
    ) -> Mapping[str, object]:
        body = {"query": query, "variables": dict(variables)}
        reused_token = self._token is not None
        try:
            payload = self._post_graphql(body)
        except _UnauthorizedError:
            # A 401 means Xray refused the call before running it, so one retry
            # with a fresh token cannot duplicate a create.
            if not reused_token:
                raise
            self._token = None
            payload = self._post_graphql(body)
        if not isinstance(payload, Mapping):
            raise ConnectorError(MSG_REQUEST_FAILED)
        return payload

    def _post_graphql(self, body: Mapping[str, object]) -> object:
        return self._request(
            "/graphql", json=body, headers={"Authorization": f"Bearer {self._bearer()}"}
        )

    def _bearer(self) -> str:
        if self._token is None:
            token = self._request(
                "/authenticate",
                json={"client_id": self._client_id, "client_secret": self._client_secret},
            )
            if not isinstance(token, str) or not token.strip():
                raise ConnectorError(MSG_REQUEST_FAILED)
            self._token = token.strip()
        return self._token

    def _request(
        self,
        path: str,
        *,
        json: object,
        headers: Mapping[str, str] | None = None,
    ) -> object:
        try:
            response = self._client.post(path, json=json, headers=headers)
            response.raise_for_status()
            return response.json()
        except Exception as error:
            mapped = map_http_error(error, self._httpx)
            cause = diagnostic(error, self._httpx)
            if isinstance(error, self._httpx.HTTPStatusError) and error.response.status_code == 401:
                mapped = _UnauthorizedError()
        # Raised outside the handler so the httpx error is not kept as __context__.
        raise mapped from cause


def _issue_summary(item: object, *, is_test: bool) -> JiraIssueSummary:
    jira = item.get("jira") if isinstance(item, Mapping) else None
    key = jira.get("key") if isinstance(jira, Mapping) else None
    summary = jira.get("summary") if isinstance(jira, Mapping) else None
    issue_type = jira.get("issuetype") if isinstance(jira, Mapping) else None
    type_id = issue_type.get("id") if isinstance(issue_type, Mapping) else None
    type_name = issue_type.get("name") if isinstance(issue_type, Mapping) else None
    if (
        not isinstance(key, str)
        or not _ISSUE_KEY.fullmatch(key)
        or not isinstance(summary, str)
        or not isinstance(type_id, str)
        or not type_id
        or not isinstance(type_name, str)
        or not type_name
    ):
        raise ConnectorError(MSG_REQUEST_FAILED)
    return JiraIssueSummary(key, summary, type_id, type_name, is_test)


def _result_key(item: object) -> str:
    jira = item.get("jira") if isinstance(item, Mapping) else None
    key = jira.get("key") if isinstance(jira, Mapping) else None
    if not isinstance(key, str) or not _ISSUE_KEY.fullmatch(key):
        raise ConnectorError(MSG_REQUEST_FAILED)
    return key


def _naming_context(item: object, story_key: str) -> StoryNamingContext:
    jira = item.get("jira") if isinstance(item, Mapping) else None
    if not isinstance(jira, Mapping):
        raise ConnectorError(MSG_REQUEST_FAILED)
    key = jira.get("key")
    summary = jira.get("summary")
    if key != story_key or not isinstance(summary, str) or not summary:
        raise ConnectorError(MSG_REQUEST_FAILED)
    parent = jira.get("parent")
    if parent is None:
        return StoryNamingContext(story_key, summary, "absent")
    if not isinstance(parent, Mapping):
        return StoryNamingContext(story_key, summary, "failed")
    epic_key = parent.get("key")
    parent_fields = parent.get("fields") if isinstance(parent.get("fields"), Mapping) else parent
    epic_summary = parent_fields.get("summary") if isinstance(parent_fields, Mapping) else None
    if (
        isinstance(epic_key, str)
        and _ISSUE_KEY.fullmatch(epic_key)
        and isinstance(epic_summary, str)
        and epic_summary
    ):
        return StoryNamingContext(
            story_key, summary, "present", epic_key=epic_key, epic_summary=epic_summary
        )
    return StoryNamingContext(story_key, summary, "failed")


def _write_failure(error: ConnectorError, *, partial: bool) -> ConnectorError:
    """Nothing is written on a 401 (auth) or another 4xx (rejected); anything else may be."""
    if partial:
        return XrayUpdateUncertainError(partial=True)
    if isinstance(error, _UnauthorizedError):
        return error
    status = getattr(error.__cause__, "status", None)
    if isinstance(status, int) and 400 <= status < 500:
        return XrayUpdateRejectedError()
    return XrayUpdateUncertainError(partial=False)


def _pick_type(test_types: list[Mapping[str, object]], *, kind: str, preferred: str) -> str | None:
    matching = [
        t
        for t in test_types
        if str(t.get("kind", "")).casefold() == kind.casefold() and isinstance(t.get("id"), str)
    ]
    for test_type in matching:
        if test_type.get("name") == preferred:
            return str(test_type["id"])
    return str(matching[0]["id"]) if matching else None
