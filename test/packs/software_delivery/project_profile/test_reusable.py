"""Reusable component extraction (#387 slice 5)."""

from __future__ import annotations

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


def test_robot_keywords_extracted_with_line_ranges() -> None:
    evidence = evidence_for_components({"oie-tests": "acme/oie-tests"})
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


def test_frontend_path_extractor_emits_route_ui_and_api_client() -> None:
    evidence = evidence_for_components({"oie-web": "acme/oie-web"})
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
                "component": "oie-web",
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
                "component": "oie-e2e",
                "files": [
                    {
                        "path": "e2e/cancel-order.spec.ts",
                        "content": "test('cancel', async () => {})\n",
                    },
                    {
                        "path": "tests/checkout.test.js",
                        "content": "test('checkout', async () => {})\n",
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
    assert "e2e/cancel-order.spec.ts" in by_kind["page_object"]
    assert "tests/checkout.test.js" in by_kind["page_object"]


def test_default_extractors_keep_frameworks_separate() -> None:
    extractors = default_extractors()
    assert [type(item).__name__ for item in extractors] == [
        "RobotKeywordExtractor",
        "FrontendPathExtractor",
        "PlaywrightSpecExtractor",
    ]


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
                "component": "oie-tests",
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
