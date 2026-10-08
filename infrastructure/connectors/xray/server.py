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

from domain.errors import ConnectorError, ConnectorUnavailableError
from domain.test_management.xray import (
    XrayImportResult,
    XrayRequiredFieldsError,
    XrayTestCreateSchema,
    XrayTestSpec,
)
from infrastructure.connectors.xray.batch import create_each
from infrastructure.connectors.xray.errors import (
    MSG_REQUEST_FAILED,
    MSG_UNAVAILABLE,
    XrayRejectedError,
    XraySchemaError,
    diagnostic,
    map_http_error,
)
from infrastructure.connectors.xray.schema import SchemaKey, XraySchemaCache

if TYPE_CHECKING:
    import httpx

_TEST_ISSUE_TYPE = "test"
_TEST_TYPE_FIELD = "com.xpandit.plugins.xray:test-type-custom-field"
_MANUAL_STEPS_FIELD = "com.xpandit.plugins.xray:manual-test-steps-custom-field"
_CUCUMBER_TYPE_FIELD = "com.xpandit.plugins.xray:automated-test-type-custom-field"
_SCENARIO_FIELD = "com.xpandit.plugins.xray:steps-editor-custom-field"
_HANDLED_SYSTEM_FIELDS = frozenset(
    {"project", "summary", "issuetype", "reporter", "description", "issuelinks"}
)
_LABEL_KEYS = ("name", "value")
_PAGE_SIZE = 100
_MAX_PAGES = 20


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


class XrayServerImporter:
    """:class:`domain.ports.XrayTestImporter` for Xray Server/Data Center."""

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
        )

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        mapping, from_cache = self._cache.get_or_discover(self._schema_key, self._discover)
        sources: dict[tuple[str, tuple[str, ...]], Mapping[str, object]] = {}
        for source_key in dict.fromkeys(spec.source_issue_key for spec in specs):
            self._required_values(mapping, source_key, sources)

        def create(spec: XrayTestSpec, current: ServerFieldMapping) -> str:
            extra = self._required_values(current, spec.source_issue_key, sources)
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
    ) -> dict[str, object]:
        if not mapping.required_fields:
            return {}
        source = self._source_fields(mapping, source_key, sources) if source_key else {}
        values: dict[str, object] = {}
        missing: list[str] = []
        for field in mapping.required_fields:
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
        mapping: ServerFieldMapping,
        source_key: str,
        sources: dict[tuple[str, tuple[str, ...]], Mapping[str, object]],
    ) -> Mapping[str, object]:
        ids = tuple(field.field_id for field in mapping.required_fields)
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

    def _rediscover(self) -> ServerFieldMapping:
        self._cache.invalidate(self._schema_key)
        mapping, _ = self._cache.get_or_discover(self._schema_key, self._discover)
        return mapping

    def _create(
        self, spec: XrayTestSpec, mapping: ServerFieldMapping, extra: Mapping[str, object]
    ) -> str:
        ready = mapping.manual_ready if spec.kind == "manual" else mapping.cucumber_ready
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
        if spec.kind == "manual":
            fields[str(mapping.test_type_field)] = {"id": mapping.manual_option}
            fields[str(mapping.steps_field)] = {
                "steps": [
                    {
                        "index": index,
                        "fields": {
                            "action": step.action,
                            "data": "",
                            "expected result": step.expected,
                        },
                    }
                    for index, step in enumerate(spec.steps, start=1)
                ]
            }
        else:
            fields[str(mapping.test_type_field)] = {"id": mapping.cucumber_option}
            fields[str(mapping.cucumber_type_field)] = {"id": mapping.scenario_option}
            fields[str(mapping.scenario_field)] = spec.gherkin
        payload: dict[str, object] = {"fields": fields}
        if spec.link_issue_key and self._link_type and mapping.has_issue_links:
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
            _TEST_TYPE_FIELD,
            _MANUAL_STEPS_FIELD,
            _CUCUMBER_TYPE_FIELD,
            _SCENARIO_FIELD,
        }:
            by_type.setdefault(custom, field)
            continue
        if (
            field.get("required") is True
            and field.get("hasDefaultValue") is not True
            and field_id not in _HANDLED_SYSTEM_FIELDS
        ):
            required.append(_required_field(field_id, field, schema))
    test_type = by_type.get(_TEST_TYPE_FIELD)
    cucumber_type = by_type.get(_CUCUMBER_TYPE_FIELD)
    return ServerFieldMapping(
        issue_type_id=issue_type_id,
        test_type_field=_field_id(test_type),
        manual_option=_option_id(test_type, "Manual"),
        steps_field=_field_id(by_type.get(_MANUAL_STEPS_FIELD)),
        cucumber_option=_option_id(test_type, "Cucumber"),
        cucumber_type_field=_field_id(cucumber_type),
        scenario_option=_option_id(cucumber_type, "Scenario"),
        scenario_field=_field_id(by_type.get(_SCENARIO_FIELD)),
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
