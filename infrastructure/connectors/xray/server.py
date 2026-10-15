"""Xray Server/Data Center importer (Jira REST ``/rest/api/2``, Personal Access Token).

Xray Server keeps tests as Jira issues, so tests are created with Jira's
create-issue endpoint plus Xray's custom fields. Field ids differ per instance;
discovery reads the project's create metadata for the ``Test`` issue type and
finds Xray fields by their custom field type key. The PAT is sent only to the
configured base URL; redirects are never followed.

Other required fields without a Jira default are filled generically: first from
the source issue's value (kept only if it matches the field's allowed values),
then from a single allowed value. Anything left fails the batch before any
create, naming the fields.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

from domain.errors import ConnectorAuthError, ConnectorError, ConnectorUnavailableError
from domain.test_management.xray import (
    IssueLookupResult,
    JiraIssueSummary,
    StoryNamingContext,
    XrayImportResult,
    XrayRequiredFieldsError,
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
    XrayHttpDiagnostic,
    XrayRejectedError,
    XraySchemaError,
    diagnostic,
    map_http_error,
)
from infrastructure.connectors.xray.details import Unreadable, confirms_definition
from infrastructure.connectors.xray.jql import jql_string
from infrastructure.connectors.xray.schema import SchemaKey, XraySchemaCache
from infrastructure.connectors.xray.server_update import (
    CUCUMBER_TYPE_FIELD,
    DETAILS_PARAMS,
    MANUAL_STEPS_FIELD,
    SCENARIO_FIELD,
    TEST_TYPE_FIELD,
    EditTarget,
    parse_issue,
    steps_value,
    update_body,
)

if TYPE_CHECKING:
    import httpx

_TEST_ISSUE_TYPE = "test"
_EPIC_LINK_CUSTOM = "com.pyxis.greenhopper.jira:gh-epic-link"
_HANDLED_SYSTEM_FIELDS = frozenset(
    {"project", "summary", "issuetype", "reporter", "description", "issuelinks"}
)
_LABEL_KEYS = ("name", "value")
_PAGE_SIZE = 100
_MAX_PAGES = 20
_UNREADABLE = object()


@dataclass(frozen=True, slots=True)
class RequiredField:
    """A required create field without a Jira default that Kernector must fill."""

    field_id: str
    name: str
    is_array: bool
    allowed: tuple[Mapping[str, object], ...] | None


@dataclass(frozen=True, slots=True)
class ServerFieldMapping:
    """Discovered Jira ids for creating Xray tests in one project."""

    issue_type_id: str
    test_type_field: str | None = None
    manual_option: str | None = None
    steps_field: str | None = None
    cucumber_option: str | None = None
    cucumber_type_field: str | None = None
    scenario_option: str | None = None
    scenario_outline_option: str | None = None
    scenario_field: str | None = None
    has_issue_links: bool = False
    required_fields: tuple[RequiredField, ...] = ()

    @property
    def manual_ready(self) -> bool:
        return None not in (
            self.test_type_field,
            self.manual_option,
            self.steps_field,
        )

    @property
    def cucumber_ready(self) -> bool:
        return None not in (
            self.test_type_field,
            self.cucumber_option,
            self.cucumber_type_field,
            self.scenario_option,
            self.scenario_field,
        )

    @property
    def outline_ready(self) -> bool:
        return self.cucumber_ready and self.scenario_outline_option is not None


class XrayServerImporter:
    """:class:`domain.ports.XrayTestImporter` and :class:`domain.ports.XrayIssueLookup`
    for Xray Server/Data Center.

    A requested story link or Scenario Outline type that cannot be sent is a
    rejection before any request; neither is ever silently dropped.
    """

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        project_key: str,
        link_type: str,
        cache: XraySchemaCache,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        import httpx

        self._httpx = httpx
        self._base_url = base_url.rstrip("/")
        self._project_key = project_key
        self._link_type = link_type.strip()
        self._cache = cache
        self._epic_link_field: str | None | object = _UNREADABLE
        self._client = httpx.Client(
            base_url=f"{self._base_url}/rest/api/2",
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {token}",
                "User-Agent": "kernector-xray-connector",
            },
        )

    def __repr__(self) -> str:
        return (
            f"XrayServerImporter(base_url={self._base_url!r}, "
            f"project_key={self._project_key!r}, token='***')"
        )

    @property
    def _schema_key(self) -> SchemaKey:
        return ("server", self._base_url, self._project_key)

    def schema(self) -> XrayTestCreateSchema:
        mapping, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        return XrayTestCreateSchema(
            project_key=self._project_key,
            supports_manual=mapping.manual_ready,
            supports_cucumber=mapping.cucumber_ready,
            supports_issue_link=mapping.has_issue_links and bool(self._link_type),
            supports_cucumber_outline=mapping.outline_ready,
        )

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        mapping, from_cache = self._cache.get_or_discover(self._schema_key, self._discover)
        sources: dict[tuple[str, tuple[str, ...]], Mapping[str, object]] = {}
        for source_key, skip in dict.fromkeys(
            (spec.source_issue_key, _overridden(spec)) for spec in specs
        ):
            self._required_values(mapping, source_key, sources, skip)

        def create(spec: XrayTestSpec, current: ServerFieldMapping) -> str:
            extra = self._required_values(
                current, spec.source_issue_key, sources, _overridden(spec)
            )
            return self._create(spec, current, extra)

        return create_each(
            specs,
            mapping=mapping,
            from_cache=from_cache,
            rediscover=self._rediscover,
            create=create,
        )

    def _required_values(
        self,
        mapping: ServerFieldMapping,
        source_key: str | None,
        sources: dict[tuple[str, tuple[str, ...]], Mapping[str, object]],
        skip: frozenset[str] = frozenset(),
    ) -> dict[str, object]:
        required = tuple(f for f in mapping.required_fields if f.field_id not in skip)
        if not required:
            return {}
        source = self._source_fields(required, source_key, sources) if source_key else {}
        values: dict[str, object] = {}
        missing: list[str] = []
        for field in required:
            value = _resolve(field, source.get(field.field_id))
            if value is None:
                missing.append(field.name)
            else:
                values[field.field_id] = value
        if missing:
            raise XrayRequiredFieldsError(tuple(missing))
        return values

    def _source_fields(
        self,
        required: tuple[RequiredField, ...],
        source_key: str,
        sources: dict[tuple[str, tuple[str, ...]], Mapping[str, object]],
    ) -> Mapping[str, object]:
        ids = tuple(field.field_id for field in required)
        memo_key = (source_key, ids)
        if memo_key not in sources:
            payload = self._request(
                "GET",
                f"/issue/{quote(source_key, safe='')}",
                params={"fields": ",".join(ids)},
                missing_ok=True,
            )
            fields = payload.get("fields") if isinstance(payload, Mapping) else None
            sources[memo_key] = fields if isinstance(fields, Mapping) else {}
        return sources[memo_key]

    def find_issues(self, keys: Sequence[str]) -> IssueLookupResult:
        """Read each key; only a 404 counts as missing, every other failure raises."""
        mapping, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        found: dict[str, JiraIssueSummary] = {}
        missing: set[str] = set()
        for key in dict.fromkeys(keys):
            payload = self._request(
                "GET",
                f"/issue/{quote(key, safe='')}",
                params={"fields": "issuetype,summary"},
                missing_ok=True,
            )
            if payload is None:
                missing.add(key)
            else:
                found[key] = _issue_summary(payload, mapping.issue_type_id)
        return IssueLookupResult(found=found, missing=frozenset(missing))

    def linked_tests(self, story_key: str) -> tuple[JiraIssueSummary, ...]:
        """Test issues linked to ``story_key`` in either direction; malformed links raise."""
        mapping, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        payload = self._request(
            "GET", f"/issue/{quote(story_key, safe='')}", params={"fields": "issuelinks"}
        )
        fields = payload.get("fields") if isinstance(payload, Mapping) else None
        links = fields.get("issuelinks") if isinstance(fields, Mapping) else None
        if not isinstance(links, list):
            raise ConnectorError(MSG_REQUEST_FAILED)
        tests: list[JiraIssueSummary] = []
        for link in links:
            issue = None
            if isinstance(link, Mapping):
                issue = link.get("outwardIssue") or link.get("inwardIssue")
            if not isinstance(issue, Mapping):
                raise ConnectorError(MSG_REQUEST_FAILED)
            summary = _issue_summary(issue, mapping.issue_type_id)
            if summary.is_test:
                tests.append(summary)
        return tuple(tests)

    def list_tests(
        self, project_key: str, *, component: str | None = None
    ) -> tuple[JiraIssueSummary, ...]:
        """Every Test in ``project_key`` via Jira search; optional component filter."""
        mapping, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        if not project_key.strip():
            raise ConnectorError(MSG_REQUEST_FAILED)
        clauses = [f"project = {jql_string(project_key.strip())}", "issuetype = Test"]
        if component is not None:
            if not component.strip():
                raise ConnectorError(MSG_REQUEST_FAILED)
            clauses.append(f"component = {jql_string(component.strip())}")
        jql = " AND ".join(clauses)
        by_key: dict[str, JiraIssueSummary] = {}
        start_at = 0
        for _ in range(_MAX_PAGES):
            payload = self._request(
                "GET",
                "/search",
                params={
                    "jql": jql,
                    "startAt": str(start_at),
                    "maxResults": str(_PAGE_SIZE),
                    "fields": "summary,issuetype",
                },
            )
            if not isinstance(payload, Mapping):
                raise ConnectorError(MSG_REQUEST_FAILED)
            issues = payload.get("issues")
            total = payload.get("total")
            if not isinstance(issues, list) or not isinstance(total, int) or isinstance(total, bool):
                raise ConnectorError(MSG_REQUEST_FAILED)
            if not issues:
                if start_at >= total:
                    return tuple(by_key.values())
                raise ConnectorError(MSG_REQUEST_FAILED)
            page_keys: list[str] = []
            for issue in issues:
                summary = _issue_summary(issue, mapping.issue_type_id)
                if summary.key in by_key or summary.key in page_keys:
                    raise ConnectorUnavailableError(MSG_UNAVAILABLE)
                page_keys.append(summary.key)
                by_key[summary.key] = summary
            start_at += len(issues)
            if start_at >= total:
                return tuple(by_key.values())
        raise ConnectorUnavailableError(MSG_UNAVAILABLE)

    def story_naming_context(self, story_key: str) -> StoryNamingContext:
        """Story summary plus parent or discovered Epic Link field."""
        epic_field = self._resolve_epic_link_field()
        field_ids = ["summary", "issuetype", "parent"]
        if epic_field:
            field_ids.append(epic_field)
        payload = self._request(
            "GET",
            f"/issue/{quote(story_key, safe='')}",
            params={"fields": ",".join(field_ids)},
            missing_ok=True,
        )
        if payload is None:
            raise ConnectorError(MSG_REQUEST_FAILED)
        fields = payload.get("fields") if isinstance(payload, Mapping) else None
        key = payload.get("key") if isinstance(payload, Mapping) else None
        summary = fields.get("summary") if isinstance(fields, Mapping) else None
        if key != story_key or not isinstance(summary, str) or not summary:
            raise ConnectorError(MSG_REQUEST_FAILED)
        naming = _story_naming(
            story_key, summary, fields if isinstance(fields, Mapping) else {}, epic_field
        )
        if naming.epic_presence != "failed" or epic_field is None or not isinstance(fields, Mapping):
            return naming
        raw = fields.get(epic_field)
        if not isinstance(raw, str) or not raw.strip():
            return naming
        epic = self._request(
            "GET",
            f"/issue/{quote(raw.strip(), safe='')}",
            params={"fields": "summary"},
            missing_ok=True,
        )
        if epic is None:
            return StoryNamingContext(story_key, summary, "failed")
        epic_fields = epic.get("fields") if isinstance(epic, Mapping) else None
        epic_key = epic.get("key") if isinstance(epic, Mapping) else None
        epic_summary = epic_fields.get("summary") if isinstance(epic_fields, Mapping) else None
        if (
            isinstance(epic_key, str)
            and epic_key
            and isinstance(epic_summary, str)
            and epic_summary
        ):
            return StoryNamingContext(
                story_key, summary, "present", epic_key=epic_key, epic_summary=epic_summary
            )
        return StoryNamingContext(story_key, summary, "failed")

    def capabilities(self) -> XrayUpdateCapabilities:
        """Jira fields are writable here; the story link needs a known link type."""
        payload = self._request("GET", "/issueLinkType")
        types = payload.get("issueLinkTypes") if isinstance(payload, Mapping) else None
        if not isinstance(types, list):
            raise ConnectorError(MSG_REQUEST_FAILED)
        names = {t.get("name") for t in types if isinstance(t, Mapping)}
        return XrayUpdateCapabilities(
            jira_fields=True, story_link_type=bool(self._link_type) and self._link_type in names
        )

    def test_details(self, keys: Sequence[str]) -> XrayTestDetailsResult:
        """Read each test; a 404 is left out, malformed answers are unreadable."""
        found: dict[str, XrayTestDetails] = {}
        unreadable: set[str] = set()
        for key in dict.fromkeys(keys):
            read = self._read_test(key)
            if read is _UNREADABLE:
                unreadable.add(key)
            elif read is not None:
                found[key] = read[0]
        return XrayTestDetailsResult(found=found, unreadable=frozenset(unreadable))

    def update_test(self, patch: XrayTestPatch) -> None:
        """One sparse ``PUT``; a kind switch is read back to confirm the old definition is gone.

        A test outside the configured project is rejected before the ``PUT``.
        """
        current = self._read_test(patch.key)
        body = (
            update_body(patch, current[1])
            if isinstance(current, tuple) and current[0].project_key == self._project_key
            else None
        )
        if body is None:
            raise XrayUpdateRejectedError()
        self._put(f"/issue/{quote(patch.key, safe='')}", body)
        if patch.kind_change is None:
            return
        try:
            after = self._read_test(patch.key)
        except ConnectorError:
            after = None
        if not isinstance(after, tuple) or not confirms_definition(patch, after[0]):
            raise XrayUpdateNotConfirmedError()

    def _put(self, path: str, body: Mapping[str, object]) -> None:
        """``PUT`` with update outcomes: 401 is auth, other 4xx rejected, else uncertain."""
        failure: ConnectorError
        try:
            response = self._client.request("PUT", path, json=body)
        except Exception as error:
            failure, cause = XrayUpdateUncertainError(partial=False), diagnostic(error, self._httpx)
        else:
            status = response.status_code
            if 200 <= status < 300:
                return
            if status == 401:
                failure = ConnectorAuthError(MSG_AUTH)
            elif 400 <= status < 500:
                failure = XrayUpdateRejectedError()
            else:
                failure = XrayUpdateUncertainError(partial=False)
            cause = XrayHttpDiagnostic(f"HTTP {status}", status)
        # Raised outside the handler so the httpx error is not kept as __context__.
        raise failure from cause

    def _read_test(
        self, key: str
    ) -> tuple[XrayTestDetails, EditTarget] | None | object:
        payload = self._request(
            "GET", f"/issue/{quote(key, safe='')}", params=DETAILS_PARAMS, missing_ok=True
        )
        if payload is None:
            return None
        try:
            return parse_issue(key, payload)
        except Unreadable:
            return _UNREADABLE

    def _rediscover(self) -> ServerFieldMapping:
        self._cache.invalidate(self._schema_key)
        mapping, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        return mapping

    def _create(
        self, spec: XrayTestSpec, mapping: ServerFieldMapping, extra: Mapping[str, object]
    ) -> str:
        ready = mapping.manual_ready if spec.kind == "manual" else mapping.cucumber_ready
        if spec.kind == "cucumber" and spec.outline:
            ready = mapping.outline_ready
        if spec.link_issue_key and not (self._link_type and mapping.has_issue_links):
            ready = False
        if not ready:
            raise XrayRejectedError()
        payload = self._request("POST", "/issue", json=self._issue_payload(spec, mapping, extra))
        key = payload.get("key") if isinstance(payload, Mapping) else None
        if not isinstance(key, str) or not key:
            raise ConnectorError(MSG_REQUEST_FAILED)
        return key

    def _issue_payload(
        self, spec: XrayTestSpec, mapping: ServerFieldMapping, extra: Mapping[str, object]
    ) -> dict[str, object]:
        fields: dict[str, object] = {
            **extra,
            "project": {"key": self._project_key},
            "summary": spec.title,
            "issuetype": {"id": mapping.issue_type_id},
        }
        if spec.preconditions:
            fields["description"] = spec.preconditions
        if spec.component:
            fields["components"] = [{"name": spec.component}]
        if spec.kind == "manual":
            fields[str(mapping.test_type_field)] = {"id": mapping.manual_option}
            fields[str(mapping.steps_field)] = steps_value(spec.steps)
        else:
            fields[str(mapping.test_type_field)] = {"id": mapping.cucumber_option}
            option = mapping.scenario_outline_option if spec.outline else mapping.scenario_option
            fields[str(mapping.cucumber_type_field)] = {"id": option}
            fields[str(mapping.scenario_field)] = spec.gherkin
        payload: dict[str, object] = {"fields": fields}
        if spec.link_issue_key:
            payload["update"] = {
                "issuelinks": [
                    {
                        "add": {
                            "type": {"name": self._link_type},
                            "outwardIssue": {"key": spec.link_issue_key},
                        }
                    }
                ]
            }
        return payload

    def _discover(self) -> ServerFieldMapping:
        project = quote(self._project_key, safe="")
        issue_types = self._paged(f"/issue/createmeta/{project}/issuetypes")
        issue_type_id = next(
            (
                str(t["id"])
                for t in issue_types
                if isinstance(t.get("id"), str)
                and str(t.get("name", "")).strip().lower() == _TEST_ISSUE_TYPE
            ),
            None,
        )
        if issue_type_id is None:
            raise XraySchemaError()
        fields = self._paged(
            f"/issue/createmeta/{project}/issuetypes/{quote(issue_type_id, safe='')}"
        )
        return _mapping(issue_type_id, fields)

    def _resolve_epic_link_field(self) -> str | None:
        """Discover the Epic Link custom field id once; ``None`` when the instance has none."""
        if self._epic_link_field is not _UNREADABLE:
            return self._epic_link_field if isinstance(self._epic_link_field, str) else None
        payload = self._request("GET", "/field")
        if not isinstance(payload, list):
            raise ConnectorError(MSG_REQUEST_FAILED)
        field_id: str | None = None
        for field in payload:
            if not isinstance(field, Mapping):
                continue
            schema = field.get("schema")
            custom = schema.get("custom") if isinstance(schema, Mapping) else None
            fid = field.get("id")
            if custom == _EPIC_LINK_CUSTOM and isinstance(fid, str) and fid:
                if field_id is not None:
                    raise ConnectorError(MSG_REQUEST_FAILED)
                field_id = fid
        self._epic_link_field = field_id
        return field_id

    def _paged(self, path: str) -> list[Mapping[str, object]]:
        values: list[Mapping[str, object]] = []
        start_at = 0
        for _ in range(_MAX_PAGES):
            payload = self._request(
                "GET", path, params={"startAt": str(start_at), "maxResults": str(_PAGE_SIZE)}
            )
            if not isinstance(payload, Mapping):
                raise ConnectorError(MSG_REQUEST_FAILED)
            page = payload.get("values")
            if not isinstance(page, list):
                raise ConnectorError(MSG_REQUEST_FAILED)
            values.extend(v for v in page if isinstance(v, Mapping))
            if payload.get("isLast", True) is True:
                return values
            if not page:
                break
            start_at += len(page)
        raise ConnectorUnavailableError(MSG_UNAVAILABLE)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: object = None,
        params: Mapping[str, str] | None = None,
        missing_ok: bool = False,
    ) -> object:
        try:
            response = self._client.request(method, path, json=json, params=params)
            if missing_ok and response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()
        except Exception as error:
            mapped = map_http_error(error, self._httpx)
            cause = diagnostic(error, self._httpx)
        # Raised outside the handler so the httpx error is not kept as __context__.
        raise mapped from cause


def _overridden(spec: XrayTestSpec) -> frozenset[str]:
    """Required fields the spec sets itself, so they skip default/inheritance resolution."""
    return frozenset({"components"}) if spec.component else frozenset()


def _issue_summary(payload: object, test_type_id: str) -> JiraIssueSummary:
    fields = payload.get("fields") if isinstance(payload, Mapping) else None
    issue_type = fields.get("issuetype") if isinstance(fields, Mapping) else None
    key = payload.get("key") if isinstance(payload, Mapping) else None
    summary = fields.get("summary") if isinstance(fields, Mapping) else None
    type_id = issue_type.get("id") if isinstance(issue_type, Mapping) else None
    type_name = issue_type.get("name") if isinstance(issue_type, Mapping) else None
    if not all(isinstance(v, str) and v for v in (key, type_id, type_name)) or not isinstance(
        summary, str
    ):
        raise ConnectorError(MSG_REQUEST_FAILED)
    return JiraIssueSummary(
        key=str(key),
        summary=summary,
        issue_type_id=str(type_id),
        issue_type_name=str(type_name),
        is_test=type_id == test_type_id,
    )


def _story_naming(
    story_key: str,
    summary: str,
    fields: Mapping[str, object],
    epic_field: str | None,
) -> StoryNamingContext:
    parent = fields.get("parent")
    epic_from_parent = _epic_from_parent(parent)
    if epic_from_parent is not None:
        return StoryNamingContext(
            story_key,
            summary,
            "present",
            epic_key=epic_from_parent[0],
            epic_summary=epic_from_parent[1],
        )
    if parent is not None and not isinstance(parent, Mapping):
        return StoryNamingContext(story_key, summary, "failed")
    if epic_field is None:
        return StoryNamingContext(story_key, summary, "absent")
    raw = fields.get(epic_field)
    if raw is None or raw == "":
        return StoryNamingContext(story_key, summary, "absent")
    if isinstance(raw, str) and raw.strip():
        # Epic Link often stores only the epic key; summary requires a follow-up read
        # the caller performs via present only when both are known — key alone is failed.
        return StoryNamingContext(story_key, summary, "failed")
    if isinstance(raw, Mapping):
        epic = _epic_from_parent(raw)
        if epic is not None:
            return StoryNamingContext(
                story_key, summary, "present", epic_key=epic[0], epic_summary=epic[1]
            )
    return StoryNamingContext(story_key, summary, "failed")


def _epic_from_parent(parent: object) -> tuple[str, str] | None:
    if not isinstance(parent, Mapping):
        return None
    epic_key = parent.get("key")
    parent_fields = parent.get("fields") if isinstance(parent.get("fields"), Mapping) else parent
    epic_summary = parent_fields.get("summary") if isinstance(parent_fields, Mapping) else None
    if isinstance(epic_key, str) and epic_key and isinstance(epic_summary, str) and epic_summary:
        return epic_key, epic_summary
    return None


def _mapping(issue_type_id: str, fields: list[Mapping[str, object]]) -> ServerFieldMapping:
    by_type: dict[str, Mapping[str, object]] = {}
    required: list[RequiredField] = []
    has_issue_links = False
    for field in fields:
        field_id = field.get("fieldId")
        if not isinstance(field_id, str):
            continue
        schema = field.get("schema")
        custom = schema.get("custom") if isinstance(schema, Mapping) else None
        if field_id == "issuelinks":
            has_issue_links = True
        if isinstance(custom, str) and custom in {
            TEST_TYPE_FIELD,
            MANUAL_STEPS_FIELD,
            CUCUMBER_TYPE_FIELD,
            SCENARIO_FIELD,
        }:
            by_type.setdefault(custom, field)
            continue
        if (
            field.get("required") is True
            and field.get("hasDefaultValue") is not True
            and field_id not in _HANDLED_SYSTEM_FIELDS
        ):
            required.append(_required_field(field_id, field, schema))
    test_type = by_type.get(TEST_TYPE_FIELD)
    cucumber_type = by_type.get(CUCUMBER_TYPE_FIELD)
    return ServerFieldMapping(
        issue_type_id=issue_type_id,
        test_type_field=_field_id(test_type),
        manual_option=_option_id(test_type, "Manual"),
        steps_field=_field_id(by_type.get(MANUAL_STEPS_FIELD)),
        cucumber_option=_option_id(test_type, "Cucumber"),
        cucumber_type_field=_field_id(cucumber_type),
        scenario_option=_option_id(cucumber_type, "Scenario"),
        scenario_outline_option=_option_id(cucumber_type, "Scenario Outline"),
        scenario_field=_field_id(by_type.get(SCENARIO_FIELD)),
        has_issue_links=has_issue_links,
        required_fields=tuple(required),
    )


def _required_field(
    field_id: str, field: Mapping[str, object], schema: object
) -> RequiredField:
    name = field.get("name")
    options = field.get("allowedValues")
    return RequiredField(
        field_id=field_id,
        name=name if isinstance(name, str) and name.strip() else field_id,
        is_array=isinstance(schema, Mapping) and schema.get("type") == "array",
        allowed=(
            tuple(o for o in options if isinstance(o, Mapping))
            if isinstance(options, list)
            else None
        ),
    )


def _resolve(field: RequiredField, source_value: object) -> object | None:
    """Create-ready value for ``field``, or ``None`` when it cannot be filled."""
    candidates = source_value if isinstance(source_value, list) else [source_value]
    picked = [
        ref for ref in (_reference(c, field.allowed) for c in candidates) if ref is not None
    ]
    if picked:
        return picked if field.is_array else picked[0]
    if field.allowed is not None and len(field.allowed) == 1:
        only = _option_reference(field.allowed[0])
        if only is not None:
            return [only] if field.is_array else only
    return None


def _reference(value: object, allowed: tuple[Mapping[str, object], ...] | None) -> object | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if allowed is not None:
        option = _matching_option(value, allowed)
        return _option_reference(option) if option is not None else None
    if isinstance(value, str | int | float):
        return value
    if isinstance(value, Mapping):
        return _option_reference(value)
    return None


def _matching_option(
    value: object, allowed: tuple[Mapping[str, object], ...]
) -> Mapping[str, object] | None:
    if isinstance(value, Mapping):
        value_id = value.get("id")
        if value_id is not None:
            for option in allowed:
                if option.get("id") == value_id:
                    return option
        labels = {value.get(k) for k in _LABEL_KEYS} - {None}
    else:
        labels = {value}
    for option in allowed:
        if any(option.get(k) in labels for k in _LABEL_KEYS):
            return option
    return None


def _option_reference(option: Mapping[str, object]) -> dict[str, object] | None:
    for key in ("id", *_LABEL_KEYS, "key"):
        value = option.get(key)
        if isinstance(value, str | int) and not isinstance(value, bool) and value != "":
            return {key: str(value) if key == "id" else value}
    return None


def _field_id(field: Mapping[str, object] | None) -> str | None:
    return str(field["fieldId"]) if field is not None else None


def _option_id(field: Mapping[str, object] | None, value: str) -> str | None:
    options = field.get("allowedValues") if field is not None else None
    if not isinstance(options, list):
        return None
    for option in options:
        if isinstance(option, Mapping) and option.get("value") == value:
            option_id = option.get("id")
            return str(option_id) if option_id is not None else None
    return None
