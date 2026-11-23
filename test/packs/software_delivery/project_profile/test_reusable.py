"""Reusable component extraction (#387 slice 5)."""

from __future__ import annotations

import pytest

from test.packs.software_delivery.project_profile.conftest import (
    a0_evidence,
    evidence_for_components,
)

from packs.software_delivery.project_profile.intake import ingest_profile_evidence
from packs.software_delivery.project_profile.models import (
    LineRange,
    ReusableComponent,
)
from packs.software_delivery.project_profile.extractors import default_extractors
from packs.software_delivery.project_profile.extractors.frontend_paths import (
    FrontendPathExtractor,
)
from packs.software_delivery.project_profile.extractors.playwright_specs import (
    PlaywrightSpecExtractor,
)
from packs.software_delivery.project_profile.extractors.robot_keywords import (
    RobotKeywordExtractor,
)
from packs.software_delivery.project_profile.reusable import (
    ReusableComponentSource,
    collect_reusable_components,
)


def test_robot_suite_keywords_are_not_extracted_as_reusable() -> None:
    content = (
        "*** Test Cases ***\n"
        "Login\n"
        "    Log In As Admin\n"
        "\n"
        "*** Keywords ***\n"
        "Log In As Admin\n"
        "    No Operation\n"
    )
    evidence = ingest_profile_evidence(
        [{"files": [{"path": "tests/login.robot", "content": content}]}]
    )
    components, diagnostics = RobotKeywordExtractor().extract(
        "", evidence.components[0].files
    )
    assert components == ()
    assert any("Test Cases or Tasks" in item for item in diagnostics)


def test_robot_tasks_suite_keywords_are_not_extracted() -> None:
    content = (
        "*** Tasks ***\n"
        "Nightly Login\n"
        "    Log In As Admin\n"
        "\n"
        "*** Keywords ***\n"
        "Log In As Admin\n"
        "    No Operation\n"
    )
    evidence = ingest_profile_evidence(
        [{"files": [{"path": "tasks/login.robot", "content": content}]}]
    )
    components, diagnostics = RobotKeywordExtractor().extract(
        "", evidence.components[0].files
    )
    assert components == ()
    assert any("Test Cases or Tasks" in item for item in diagnostics)


@pytest.mark.parametrize(
    "header",
    [
        "*** Test Cases ***    USERNAME    PASSWORD",
        "*** Test Case ***",
        "*** Task ***",
        "* Test Cases",
        "* Tasks ***",
    ],
)
def test_robot_suite_header_variants_are_not_extracted(header: str) -> None:
    content = (
        f"{header}\n"
        "Login\n"
        "    Log In As Admin\n"
        "\n"
        "*** Keywords ***\n"
        "Log In As Admin\n"
        "    No Operation\n"
    )
    evidence = ingest_profile_evidence(
        [{"files": [{"path": "tests/login_data_driven.robot", "content": content}]}]
    )
    components, diagnostics = RobotKeywordExtractor().extract(
        "", evidence.components[0].files
    )
    assert components == ()
    assert any("Test Cases or Tasks" in item for item in diagnostics)


def test_robot_keyword_only_robot_file_is_extracted() -> None:
    content = (
        "*** Keywords ***\n"
        "Log In As Admin\n"
        "    No Operation\n"
    )
    evidence = ingest_profile_evidence(
        [{"files": [{"path": "resources/common.robot", "content": content}]}]
    )
    components, _diagnostics = RobotKeywordExtractor().extract(
        "", evidence.components[0].files
    )
    assert [item.signature for item in components] == ["Log In As Admin"]
    assert components[0].path == "resources/common.robot"


def test_robot_keywords_extracted_with_line_ranges() -> None:
    evidence = evidence_for_components({"proj-tests": "acme/proj-tests"})
    components = collect_reusable_components(
        evidence, extractors=(RobotKeywordExtractor(),)
    )
    by_sig = {c.signature: c for c in components}
    assert set(by_sig) >= {
        "Create Unpaid Order",
        "Create Paid Order",
        "Cancel Order",
    }
    assert by_sig["Create Unpaid Order"].line_range == LineRange(2, 4)
    assert by_sig["Create Paid Order"].line_range == LineRange(6, 8)
    assert by_sig["Cancel Order"].line_range == LineRange(10, 12)
    assert by_sig["Cancel Order"].kind == "keyword"
    assert by_sig["Cancel Order"].framework_id == "robot_framework"
    assert by_sig["Cancel Order"].path == "resources/orders.resource"
    assert by_sig["Cancel Order"].content_hash


def test_robot_auth_api_password_placeholder_still_extracts_keywords() -> None:
    """Redacted Robot auth keyword files must stay extractable after intake."""
    content = (
        "*** Settings ***\n"
        "Library    Collections\n"
        "\n"
        "*** Keywords ***\n"
        "User logs in using API as\n"
        "    [Arguments]    ${role}\n"
        "    ${payload}=    Create Dictionary    "
        "email=${username}    password=${password}\n"
        "    ${response}=    POST On Session    api    /login    json=${payload}\n"
        "\n"
        "User logs out using API\n"
        "    DELETE On Session    api    /logout\n"
    )
    evidence = ingest_profile_evidence(
        [
            {
                "files": [
                    {
                        "path": "resources/keywords/api/auth_api.resource",
                        "content": content,
                    }
                ]
            }
        ]
    )
    assert len(evidence.components[0].files) == 1
    components = collect_reusable_components(
        evidence, extractors=(RobotKeywordExtractor(),)
    )
    by_sig = {item.signature: item for item in components}
    assert set(by_sig) == {"User logs in using API as", "User logs out using API"}
    assert by_sig["User logs in using API as"].path == (
        "resources/keywords/api/auth_api.resource"
    )
    assert by_sig["User logs in using API as"].line_range == LineRange(5, 8)
    assert by_sig["User logs out using API"].line_range == LineRange(10, 11)


def test_frontend_path_extractor_emits_route_ui_and_api_client() -> None:
    evidence = evidence_for_components({"proj-web": "acme/proj-web"})
    components = collect_reusable_components(
        evidence, extractors=(FrontendPathExtractor(),)
    )
    by_kind = {}
    for item in components:
        by_kind.setdefault(item.kind, []).append(item)
    assert any(c.path.endswith("page.tsx") for c in by_kind["route"])
    assert any("CancelOrderButton" in c.path for c in by_kind["ui_component"])
    assert any(c.path.endswith("orders.ts") for c in by_kind["api_client"])
    for item in components:
        assert item.component_id
        assert item.signature
        assert item.content_hash
        assert item.line_range.start >= 1


def test_frontend_path_extractor_accepts_ts_js_jsx_and_playwright_specs() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "proj-web",
                "files": [
                    {"path": "app/orders/page.ts", "content": "export default {}\n"},
                    {
                        "path": "components/CancelButton.jsx",
                        "content": "export function CancelButton() {}\n",
                    },
                    {
                        "path": "lib/api/orders.js",
                        "content": "export async function cancelOrder() {}\n",
                    },
                ],
            },
            {
                "component": "proj-e2e",
                "files": [
                    {
                        "path": "e2e/cancel-order.spec.ts",
                        "content": (
                            'import { test } from "@playwright/test";\n'
                            "test('cancel', async () => {})\n"
                        ),
                    },
                    {
                        "path": "tests/checkout.test.js",
                        "content": (
                            "const { test } = require('@playwright/test');\n"
                            "test('checkout', async () => {})\n"
                        ),
                    },
                ],
            },
        ]
    )
    components = collect_reusable_components(
        evidence,
        extractors=(FrontendPathExtractor(), PlaywrightSpecExtractor()),
    )
    by_kind: dict[str, list[str]] = {}
    for item in components:
        by_kind.setdefault(item.kind, []).append(item.path)
    assert "app/orders/page.ts" in by_kind["route"]
    assert "components/CancelButton.jsx" in by_kind["ui_component"]
    assert "lib/api/orders.js" in by_kind["api_client"]
    assert "e2e/cancel-order.spec.ts" in by_kind["test_spec"]
    assert "tests/checkout.test.js" in by_kind["test_spec"]


def test_default_extractors_keep_frameworks_separate() -> None:
    extractors = default_extractors()
    assert [type(item).__name__ for item in extractors] == [
        "RobotKeywordExtractor",
        "FrontendPathExtractor",
        "PlaywrightSpecExtractor",
        "PytestFixtureExtractor",
        "CypressSupportExtractor",
        "SeleniumPageExtractor",
    ]


def test_unrelated_pages_and_jest_do_not_emit_framework_diagnostics() -> None:
    from packs.software_delivery.project_profile.extractors.selenium_pages import (
        SeleniumPageExtractor,
    )

    evidence = ingest_profile_evidence(
        [
            {
                "component": "web",
                "files": [
                    {
                        "path": "pages/index.js",
                        "content": "export default function Home() { return null }\n",
                    },
                    {
                        "path": "pages/about.js",
                        "content": "export default function About() { return null }\n",
                    },
                    {
                        "path": "src/utils/sum.test.js",
                        "content": "test('adds', () => { expect(1+1).toBe(2) })\n",
                    },
                ],
            }
        ]
    )
    _, diagnostics = collect_reusable_components(
        evidence,
        extractors=(PlaywrightSpecExtractor(), SeleniumPageExtractor()),
        return_diagnostics=True,
    )
    assert not any("selenium" in d for d in diagnostics)
    assert not any("playwright" in d for d in diagnostics)


def test_insufficient_recommendations_cover_js_ts_and_playwright() -> None:
    from packs.software_delivery.project_profile.detectors import (
        default_detector_registry,
    )
    from packs.software_delivery.project_profile.registry import (
        recommendations_for_facet,
    )

    registry = default_detector_registry()
    test_recs = recommendations_for_facet(registry, "test_frameworks")
    assert "**/*.spec.ts" in test_recs
    assert "**/*.spec.js" in test_recs
    reusable_recs = recommendations_for_facet(registry, "reusable_components")
    assert "components/**/*.ts" in reusable_recs
    assert "components/**/*.js" in reusable_recs
    assert "components/**/*.jsx" in reusable_recs
    assert "e2e/**/*.ts" in reusable_recs
    assert "**/*.spec.ts" in reusable_recs


def test_fake_298_source_preserves_provenance() -> None:
    evidence = a0_evidence()
    original = ReusableComponent(
        component_id="step:cancel-order",
        kind="step_definition",
        framework_id="cucumber",
        signature="I cancel the order",
        path="features/steps/orders.py",
        content_hash="abc",
        line_range=LineRange(10, 20),
        documentation="from catalogue",
    )

    class FakeCatalogue:
        def list_components(self, evidence_payload):
            return (original,)

    source: ReusableComponentSource = FakeCatalogue()
    components = collect_reusable_components(
        evidence, extractors=(), sources=(source,)
    )
    assert components == (original,)


def test_unsupported_robot_forms_produce_diagnostics() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "proj-tests",
                "files": [
                    {
                        "path": "resources/bad.resource",
                        "content": "*** Keywords ***\n"
                        "${dynamic} Keyword\n    No Operation\n",
                    }
                ],
            }
        ]
    )
    components, diagnostics = collect_reusable_components(
        evidence, extractors=(RobotKeywordExtractor(),), return_diagnostics=True
    )
    assert components == ()
    assert any("unsupported" in d.lower() for d in diagnostics)
