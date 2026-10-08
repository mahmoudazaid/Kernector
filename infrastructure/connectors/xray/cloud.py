"""Xray Cloud importer (GraphQL API v2, client-credentials authentication).

Discovery reads the project's test types (``getProjectSettings``); a manual
test needs a ``Steps`` kind and a Cucumber test a ``Gherkin`` kind. Cloud API
keys cannot read Jira link metadata, so link support follows the configured
link type name. The client secret and bearer token are sent only to the
configured base URL; redirects are never followed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.errors import ConnectorAuthError, ConnectorError
from domain.test_management.xray import XrayImportResult, XrayTestCreateSchema, XrayTestSpec
from infrastructure.connectors.xray.batch import create_each
from infrastructure.connectors.xray.errors import (
    MSG_AUTH,
    MSG_REQUEST_FAILED,
    XrayRejectedError,
    XraySchemaError,
    diagnostic,
    map_http_error,
)
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
    'gherkin: $gherkin, jira: $jira) { test { issueId jira(fields: ["key"]) } warnings } }'
)


class _UnauthorizedError(ConnectorAuthError):
    """Xray answered HTTP 401; a cached bearer token may have expired."""

    def __init__(self) -> None:
        super().__init__(MSG_AUTH)


@dataclass(frozen=True, slots=True)
class CloudTestTypes:
    """Discovered Xray Cloud test type ids; ``None`` when the kind is missing."""

    manual_id: str | None
    cucumber_id: str | None


class XrayCloudImporter:
    """:class:`domain.ports.XrayTestImporter` for Xray Cloud."""

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
        )

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        types, from_cache = self._cache.get_or_discover(self._schema_key, self._discover)
        return create_each(
            specs,
            mapping=types,
            from_cache=from_cache,
            rediscover=self._rediscover,
            create=self._create,
        )

    def _rediscover(self) -> CloudTestTypes:
        self._cache.invalidate(self._schema_key)
        types, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        return types

    def _create(self, spec: XrayTestSpec, types: CloudTestTypes) -> str:
        type_id = types.manual_id if spec.kind == "manual" else types.cucumber_id
        if type_id is None:
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
        return key

    def _create_variables(self, spec: XrayTestSpec, type_id: str) -> dict[str, object]:
        fields: dict[str, object] = {"summary": spec.title, "project": {"key": self._project_key}}
        if spec.preconditions:
            fields["description"] = spec.preconditions
        jira: dict[str, object] = {"fields": fields}
        if spec.link_issue_key and self._link_type:
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


def _pick_type(test_types: list[Mapping[str, object]], *, kind: str, preferred: str) -> str | None:
    matching = [t for t in test_types if t.get("kind") == kind and isinstance(t.get("id"), str)]
    for test_type in matching:
        if test_type.get("name") == preferred:
            return str(test_type["id"])
    return str(matching[0]["id"]) if matching else None
