"""Xray Server/Data Center schema discovery through httpx.MockTransport."""

from __future__ import annotations

import httpx
import pytest

from domain.errors import ConnectorAuthError, ConnectorUnavailableError
from domain.test_management.xray import XrayTestCreateSchema
from infrastructure.connectors.xray.errors import XraySchemaError
from infrastructure.connectors.xray.schema import XraySchemaCache
from infrastructure.connectors.xray.server import XrayServerImporter

BASE_URL = "https://jira.example.test/jira"
TOKEN = "dc-personal-access-token-XYZ"
API = "/jira/rest/api/2"

TEST_TYPE = "com.xpandit.plugins.xray:test-type-custom-field"
MANUAL_STEPS = "com.xpandit.plugins.xray:manual-test-steps-custom-field"
CUCUMBER_TYPE = "com.xpandit.plugins.xray:automated-test-type-custom-field"
SCENARIO = "com.xpandit.plugins.xray:steps-editor-custom-field"


def _field(
    field_id: str,
    *,
    custom: str | None = None,
    required: bool = False,
    type_: str = "any",
    name: str | None = None,
    **extra,
):
    schema: dict[str, object] = {"type": type_}
    if custom:
        schema["custom"] = custom
    return {
        "fieldId": field_id,
        "name": name or field_id,
        "required": required,
        "schema": schema,
        **extra,
    }


def xray_fields() -> list[dict[str, object]]:
    return [
        _field("summary", required=True),
        _field("project", required=True),
        _field("issuetype", required=True),
        _field("reporter", required=True),
        _field("issuelinks"),
        _field(
            "customfield_10200",
            custom=TEST_TYPE,
            allowedValues=[
                {"id": "301", "value": "Manual"},
                {"id": "302", "value": "Cucumber"},
                {"id": "303", "value": "Generic"},
            ],
        ),
        _field("customfield_10004", custom=MANUAL_STEPS),
        _field(
            "customfield_10201",
            custom=CUCUMBER_TYPE,
            allowedValues=[
                {"id": "401", "value": "Scenario"},
                {"id": "402", "value": "Scenario Outline"},
            ],
        ),
        _field("customfield_10202", custom=SCENARIO),
    ]


class _Jira:
    def __init__(self, fields=None, issue_types=None) -> None:
        self.fields = xray_fields() if fields is None else fields
        self.issue_types = (
            [{"id": "10001", "name": "Story"}, {"id": "10100", "name": "Test"}]
            if issue_types is None
            else issue_types
        )
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == f"{API}/issue/createmeta/QA/issuetypes":
            return httpx.Response(200, json={"values": self.issue_types, "isLast": True})
        if path == f"{API}/issue/createmeta/QA/issuetypes/10100":
            return httpx.Response(200, json={"values": self.fields, "isLast": True})
        return httpx.Response(404)


def _importer(handler, *, cache=None, link_type: str = "Test") -> XrayServerImporter:
    return XrayServerImporter(
        base_url=BASE_URL,
        token=TOKEN,
        project_key="QA",
        link_type=link_type,
        cache=cache or XraySchemaCache(),
        transport=httpx.MockTransport(handler),
    )


def test_schema_discovers_xray_fields_from_create_metadata() -> None:
    jira = _Jira()

    schema = _importer(jira).schema()

    assert schema == XrayTestCreateSchema(
        project_key="QA",
        supports_manual=True,
        supports_cucumber=True,
        supports_issue_link=True,
    )
    types_request, fields_request = jira.requests
    assert types_request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert fields_request.url.path.endswith("/issuetypes/10100")


def test_issue_type_names_match_case_insensitively() -> None:
    jira = _Jira(issue_types=[{"id": "10100", "name": "test"}])

    assert _importer(jira).schema().supports_manual is True


@pytest.mark.parametrize(
    ("missing", "manual", "cucumber"),
    [
        ("customfield_10004", False, True),
        ("customfield_10202", True, False),
        ("customfield_10201", True, False),
        ("customfield_10200", False, False),
    ],
)
def test_missing_xray_fields_disable_the_matching_kind(
    missing: str, manual: bool, cucumber: bool
) -> None:
    fields = [f for f in xray_fields() if f["fieldId"] != missing]

    schema = _importer(_Jira(fields=fields)).schema()

    assert (schema.supports_manual, schema.supports_cucumber) == (manual, cucumber)


def test_missing_test_type_options_disable_the_matching_kind() -> None:
    fields = xray_fields()
    fields[5] = _field(
        "customfield_10200", custom=TEST_TYPE, allowedValues=[{"id": "302", "value": "Cucumber"}]
    )

    schema = _importer(_Jira(fields=fields)).schema()

    assert (schema.supports_manual, schema.supports_cucumber) == (False, True)


def test_unhandled_required_field_is_resolved_at_import_not_in_the_schema() -> None:
    fields = [*xray_fields(), _field("customfield_99999", required=True, hasDefaultValue=False)]

    schema = _importer(_Jira(fields=fields)).schema()

    assert (schema.supports_manual, schema.supports_cucumber) == (True, True)


def test_required_field_with_default_does_not_block_creation() -> None:
    fields = [*xray_fields(), _field("priority", required=True, hasDefaultValue=True)]

    assert _importer(_Jira(fields=fields)).schema().supports_manual is True


@pytest.mark.parametrize("link_type", ["", " "])
def test_link_needs_issuelinks_field_and_configured_type(link_type: str) -> None:
    assert _importer(_Jira(), link_type=link_type).schema().supports_issue_link is False
    fields = [f for f in xray_fields() if f["fieldId"] != "issuelinks"]
    assert _importer(_Jira(fields=fields)).schema().supports_issue_link is False


def test_project_without_test_issue_type_raises_schema_error() -> None:
    with pytest.raises(XraySchemaError):
        _importer(_Jira(issue_types=[{"id": "10001", "name": "Story"}])).schema()


def test_paged_create_metadata_is_followed_within_a_bound() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        start = int(request.url.params.get("startAt", "0"))
        if request.url.path.endswith("/issuetypes"):
            values = [{"id": "10100", "name": "Test"}] if start else [{"id": "1", "name": "Bug"}]
            return httpx.Response(200, json={"values": values, "isLast": bool(start)})
        fields = xray_fields()
        page = fields[:4] if start == 0 else fields[4:]
        return httpx.Response(200, json={"values": page, "isLast": start != 0})

    assert _importer(handler).schema().supports_cucumber is True
    assert len(requests) == 4


def test_unbounded_create_metadata_paging_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"values": [{"id": "1", "name": "Bug"}], "isLast": False})

    with pytest.raises(ConnectorUnavailableError):
        _importer(handler).schema()


def test_schema_is_reused_from_the_cache_without_metadata_calls() -> None:
    cache = XraySchemaCache()
    _importer(_Jira(), cache=cache).schema()
    second = _Jira()

    assert _importer(second, cache=cache).schema().supports_manual is True
    assert second.requests == []


def test_invalidated_cache_entry_is_rediscovered() -> None:
    cache = XraySchemaCache()
    _importer(_Jira(), cache=cache).schema()
    cache.invalidate(("server", BASE_URL, "QA"))
    jira = _Jira(fields=[])

    assert _importer(jira, cache=cache).schema().supports_manual is False
    assert len(jira.requests) == 2


def test_auth_failure_is_typed_and_secret_free() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=f"vendor detail {TOKEN}")

    with pytest.raises(ConnectorAuthError) as caught:
        _importer(handler).schema()

    rendered = " ".join(str(e) for e in (caught.value, caught.value.__cause__) if e)
    assert TOKEN not in rendered
    assert "vendor detail" not in rendered


def test_repr_masks_the_token() -> None:
    assert TOKEN not in repr(_importer(_Jira()))
