"""profile_project composition fixes (#387 / PR #428 review)."""

from __future__ import annotations

from test.packs.software_delivery.project_profile.conftest import load_component_files

from packs.software_delivery.project_profile.limits import MAX_PROFILE_DIAGNOSTICS
from packs.software_delivery.project_profile.service import profile_project


def test_shared_relative_paths_attribute_by_owner_label() -> None:
    same = "export const A=1\n"
    profile = profile_project(
        [
            {
                "component": "web",
                "files": [{"path": "components/Button.tsx", "content": same}],
            },
            {
                "component": "admin",
                "files": [{"path": "components/Button.tsx", "content": same}],
            },
        ]
    )
    by_label = {component.label: component for component in profile.components}
    assert len(by_label["web"].reusable_components) == 1
    assert len(by_label["admin"].reusable_components) == 1
    assert by_label["web"].reusable_components[0].path == "components/Button.tsx"
    assert by_label["admin"].reusable_components[0].path == "components/Button.tsx"
    assert by_label["web"].facet_status["reusable_components"] == "detected"
    assert by_label["admin"].facet_status["reusable_components"] == "detected"


def test_detected_playwright_does_not_emit_unrecognized_diagnostic() -> None:
    profile = profile_project(
        [{"component": "proj-e2e", "files": load_component_files("acme/proj-e2e")}]
    )
    component = profile.components[0]
    assert component.facet_status["test_frameworks"] == "detected"
    assert any(
        fact.framework_id == "playwright"
        for fact in component.facts
        if fact.facet == "test_frameworks"
    )
    assert not any("unrecognized" in diagnostic for diagnostic in profile.diagnostics)
    assert not any("unrecognized" in diagnostic for diagnostic in component.diagnostics)


def test_node_spec_without_manifest_is_insufficient_context() -> None:
    profile = profile_project(
        [
            {
                "component": "proj-e2e",
                "files": [
                    {
                        "path": "e2e/cancel-order.spec.ts",
                        "content": "test('cancel', async ({ page }) => {})\n",
                    }
                ],
            }
        ]
    )
    component = profile.components[0]
    assert component.facet_status["test_frameworks"] == "insufficient_context"
    assert any("package.json" in diagnostic for diagnostic in profile.diagnostics)
    assert not any("unrecognized" in diagnostic for diagnostic in profile.diagnostics)


def test_diagnostics_capped_after_extractor_merge() -> None:
    files = [
        {
            "path": f"resources/k{i}.resource",
            "content": (
                "*** Keywords ***\n"
                "${dynamic} Keyword One\n    No Operation\n"
                "${dynamic} Keyword Two\n    No Operation\n"
                "${dynamic} Keyword Three\n    No Operation\n"
                "${dynamic} Keyword Four\n    No Operation\n"
                "${dynamic} Keyword Five\n    No Operation\n"
            ),
        }
        for i in range(30)
    ]
    profile = profile_project([{"component": "tests", "files": files}])
    assert len(profile.diagnostics) <= MAX_PROFILE_DIAGNOSTICS
