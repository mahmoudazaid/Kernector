"""Facade/HTTP coverage for Test Design → Xray test creation from the draft page."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from composition.test_design.errors import (
    TestDesignExportFailedError,
    TestDesignUnavailableError,
    TestDesignValidationError,
    TestDesignVersionConflictError,
)
from composition.test_design.facade import TestDesignFacade
from domain.knowledge import SourceReference
from domain.test_management.xray import (
    XrayImportResult,
    XrayRequiredFieldsError,
    XrayTestCreateSchema,
    XrayTestSpec,
)
from infrastructure.config import JiraDataCenterSettings, XraySettings
from packs.software_delivery.test_design.models import (
    GeneratedTestCase,
    TestCandidate,
    TestCoverageDraft,
)
from presentation.http.app import create_app
from presentation.http.deps import get_test_design_facade
from test.composition.test_design.test_design_fakes import (
    github_sources,
    settings_with_pack,
)

DRAFT_ID = "draft-xray-1"


class _FakeImporter:
    def __init__(
        self,
        *,
        result: XrayImportResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or XrayImportResult(
            created_keys=("OIE-801", "OIE-802"), failed_count=0
        )
        self.error = error
        self.calls: list[tuple[XrayTestSpec, ...]] = []

    def schema(self) -> XrayTestCreateSchema:
        return XrayTestCreateSchema(
            project_key="OIE",
            supports_manual=True,
            supports_cucumber=True,
            supports_issue_link=True,
        )

    def import_tests(self, specs: Sequence[XrayTestSpec]) -> XrayImportResult:
        self.calls.append(tuple(specs))
        if self.error is not None:
            raise self.error
        return self.result


def _facade(
    tmp_path: Path, importer: _FakeImporter | None, *, configured: bool = True
) -> TestDesignFacade:
    settings = replace(
        settings_with_pack(workspace_id="default"),
        xray=XraySettings(deployment="server", project_key="OIE", link_type="Tests")
        if configured
        else XraySettings(),
        jira_data_center=JiraDataCenterSettings(
            base_url="https://jira.example.com/jira", token="pat"
        ),
    )
    facade = TestDesignFacade(
        settings=settings,
        store_path=tmp_path / "workspace.sqlite",
        workspace_id="default",
        sources=github_sources(),
    )
    facade._build_xray_importer = lambda: importer  # type: ignore[method-assign]
    return facade


def _seed(facade: TestDesignFacade, *, with_cases: bool = True) -> int:
    reference = SourceReference("OIE-721", "jira")
    draft = TestCoverageDraft(
        draft_id=DRAFT_ID,
        workspace_id="default",
        conversation_id="conv-1",
        source_reference=reference,
        ticket_identifier="OIE-721",
        source_provider="jira",
        status="case_editing" if with_cases else "coverage_review",
        candidates=(
            TestCandidate(
                candidate_id="cand-1",
                title="Health banner shows status",
                category="positive",
                rationale="AC",
                evidence_references=(reference,),
                selected=True,
                origin="suggested",
                test_type="manual",
            ),
        ),
        version=1,
        generated_cases=(
            (
                GeneratedTestCase(
                    candidate_id="cand-1",
                    test_type="manual",
                    automation_fit="applicable",
                    automation_rationale="",
                    availability="available",
                    preconditions="Three sites exist",
                    steps=("Open the dashboard",),
                    expected_result="Banner shows Good",
                    gherkin="",
                    user_edited=False,
                ),
            )
            if with_cases
            else ()
        ),
    )
    return facade._repository().create(draft).version


def test_export_creates_tests_links_the_source_issue_and_returns_a_receipt(
    tmp_path: Path,
) -> None:
    importer = _FakeImporter()
    facade = _facade(tmp_path, importer)
    version = _seed(facade)

    receipt = facade.export_to_xray(DRAFT_ID, expected_version=version)

    assert receipt.project_key == "OIE"
    assert receipt.created_keys == ("OIE-801", "OIE-802")
    assert receipt.failed_count == 0
    assert receipt.browse_base_url == "https://jira.example.com/jira/browse/"
    (specs,) = importer.calls
    assert [(s.title, s.link_issue_key) for s in specs] == [
        ("Health banner shows status", "OIE-721")
    ]


def test_export_can_skip_the_source_issue_link(tmp_path: Path) -> None:
    importer = _FakeImporter()
    facade = _facade(tmp_path, importer)
    version = _seed(facade)

    facade.export_to_xray(DRAFT_ID, expected_version=version, link_source_issue=False)

    assert importer.calls[0][0].link_issue_key is None


def test_status_reports_availability_and_previously_created_tests(
    tmp_path: Path,
) -> None:
    facade = _facade(tmp_path, _FakeImporter())
    version = _seed(facade)

    before = facade.xray_export_status(DRAFT_ID)
    facade.export_to_xray(DRAFT_ID, expected_version=version)
    after = facade.xray_export_status(DRAFT_ID)

    assert (before.available, before.project_key, before.created_keys) == (
        True,
        "OIE",
        (),
    )
    assert before.last_created_at is None
    assert before.link_issue_key == "OIE-721"
    assert after.created_keys == ("OIE-801", "OIE-802")
    assert after.last_created_at is not None


def test_repeated_exports_accumulate_created_keys(tmp_path: Path) -> None:
    importer = _FakeImporter()
    facade = _facade(tmp_path, importer)
    version = _seed(facade)

    facade.export_to_xray(DRAFT_ID, expected_version=version)
    importer.result = XrayImportResult(created_keys=("OIE-900",), failed_count=1)
    facade.export_to_xray(DRAFT_ID, expected_version=version)

    assert facade.xray_export_status(DRAFT_ID).created_keys == (
        "OIE-801",
        "OIE-802",
        "OIE-900",
    )


def test_status_when_xray_is_not_configured(tmp_path: Path) -> None:
    facade = _facade(tmp_path, None, configured=False)
    _seed(facade)

    status = facade.xray_export_status(DRAFT_ID)

    assert status.available is False
    assert status.project_key is None


def test_export_when_xray_is_not_configured_is_unavailable(tmp_path: Path) -> None:
    facade = _facade(tmp_path, None, configured=False)
    version = _seed(facade)

    with pytest.raises(TestDesignUnavailableError):
        facade.export_to_xray(DRAFT_ID, expected_version=version)


def test_stale_version_is_a_conflict_and_creates_nothing(tmp_path: Path) -> None:
    importer = _FakeImporter()
    facade = _facade(tmp_path, importer)
    version = _seed(facade)

    with pytest.raises(TestDesignVersionConflictError):
        facade.export_to_xray(DRAFT_ID, expected_version=version + 1)

    assert importer.calls == []


def test_draft_without_generated_cases_is_a_validation_error(tmp_path: Path) -> None:
    importer = _FakeImporter()
    facade = _facade(tmp_path, importer)
    version = _seed(facade, with_cases=False)

    with pytest.raises(TestDesignValidationError):
        facade.export_to_xray(DRAFT_ID, expected_version=version)

    assert importer.calls == []


def test_required_fields_failure_names_the_fields_and_records_nothing(
    tmp_path: Path,
) -> None:
    importer = _FakeImporter(error=XrayRequiredFieldsError(("Component/s",)))
    facade = _facade(tmp_path, importer)
    version = _seed(facade)

    with pytest.raises(TestDesignExportFailedError) as caught:
        facade.export_to_xray(DRAFT_ID, expected_version=version)

    assert "Component/s" in str(caught.value)
    assert facade.xray_export_status(DRAFT_ID).created_keys == ()


def _client(facade: TestDesignFacade) -> TestClient:
    app = create_app(cors_origins=())
    app.dependency_overrides[get_test_design_facade] = lambda: facade
    return TestClient(app)


def test_http_export_and_status(tmp_path: Path) -> None:
    facade = _facade(tmp_path, _FakeImporter())
    version = _seed(facade)
    client = _client(facade)

    created = client.post(
        f"/api/v1/test-design/drafts/{DRAFT_ID}/export/xray",
        json={"expected_version": version},
    )
    status = client.get(f"/api/v1/test-design/drafts/{DRAFT_ID}/export/xray")

    assert created.status_code == 200
    assert created.json() == {
        "project_key": "OIE",
        "created_keys": ["OIE-801", "OIE-802"],
        "created_count": 2,
        "failed_count": 0,
        "browse_base_url": "https://jira.example.com/jira/browse/",
    }
    assert status.status_code == 200
    body = status.json()
    assert body["available"] is True
    assert body["project_key"] == "OIE"
    assert body["created_keys"] == ["OIE-801", "OIE-802"]
    assert isinstance(body["last_created_at"], str)
    assert body["link_issue_key"] == "OIE-721"


def test_http_required_fields_failure_is_a_502_naming_the_fields(
    tmp_path: Path,
) -> None:
    facade = _facade(
        tmp_path, _FakeImporter(error=XrayRequiredFieldsError(("Component/s",)))
    )
    version = _seed(facade)

    response = _client(facade).post(
        f"/api/v1/test-design/drafts/{DRAFT_ID}/export/xray",
        json={"expected_version": version},
    )

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "xray_export_failed"
    assert "Component/s" in body["detail"]


def test_http_stale_version_is_409(tmp_path: Path) -> None:
    facade = _facade(tmp_path, _FakeImporter())
    version = _seed(facade)

    response = _client(facade).post(
        f"/api/v1/test-design/drafts/{DRAFT_ID}/export/xray",
        json={"expected_version": version + 1},
    )

    assert response.status_code == 409
