"""Playwright depth detection and evidence-backed reusable kinds (#429 slice 1)."""

from __future__ import annotations

from packs.software_delivery.project_profile.detectors import default_detector_registry
from packs.software_delivery.project_profile.detectors.playwright import (
    PlaywrightDetector,
)
from packs.software_delivery.project_profile.extractors.playwright_specs import (
    PlaywrightSpecExtractor,
)
from packs.software_delivery.project_profile.intake import ingest_profile_evidence
from packs.software_delivery.project_profile.registry import (
    TechnologyDetectorRegistry,
    aggregate_profile,
)
from packs.software_delivery.project_profile.reusable import collect_reusable_components
from test.packs.software_delivery.project_profile.conftest import a0_evidence


def test_playwright_config_emits_test_root_convention() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "e2e",
                "files": [
                    {
                        "path": "package.json",
                        "content": '{"devDependencies":{"@playwright/test":"1.48.0"}}\n',
                    },
                    {
                        "path": "playwright.config.ts",
                        "content": (
                            "import { defineConfig } from '@playwright/test';\n"
                            "export default defineConfig({ testDir: './tests' });\n"
                        ),
                    },
                ],
            }
        ]
    )
    profile = aggregate_profile(
        evidence, TechnologyDetectorRegistry((PlaywrightDetector(),))
    )
    component = profile.components[0]
    assert any(
        c.name == "test_root" and "tests" in c.value for c in component.conventions
    )
    assert any(f.framework_id == "playwright" for f in component.facts)


def test_playwright_spec_with_api_content_is_test_spec_not_page_object() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "e2e",
                "files": [
                    {
                        "path": "e2e/cancel.spec.ts",
                        "content": (
                            'import { test, expect } from "@playwright/test";\n'
                            'test("cancel", async ({ page }) => {\n'
                            '  await expect(page.getByText("ok")).toBeVisible();\n'
                            "});\n"
                        ),
                    }
                ],
            }
        ]
    )
    components, diagnostics = collect_reusable_components(
        evidence, extractors=(PlaywrightSpecExtractor(),), return_diagnostics=True
    )
    assert len(components) == 1
    assert components[0].kind == "test_spec"
    assert components[0].framework_id == "playwright"
    assert components[0].path == "e2e/cancel.spec.ts"
    assert components[0].content_hash
    assert components[0].line_range.start == 1
    assert diagnostics == ()


def test_path_only_spec_without_content_signals_yields_diagnostic() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "e2e",
                "files": [
                    {
                        "path": "e2e/empty.spec.ts",
                        "content": "// placeholder\n",
                    }
                ],
            }
        ]
    )
    components, diagnostics = collect_reusable_components(
        evidence, extractors=(PlaywrightSpecExtractor(),), return_diagnostics=True
    )
    assert components == ()
    assert any("insufficient" in d.lower() or "no static" in d.lower() for d in diagnostics)


def test_page_object_helper_fixture_hook_require_content_evidence() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "e2e",
                "files": [
                    {
                        "path": "pages/orders.page.ts",
                        "content": (
                            "import type { Page } from '@playwright/test';\n"
                            "export class OrdersPage {\n"
                            "  constructor(private readonly page: Page) {}\n"
                            "  async open() { await this.page.goto('/orders'); }\n"
                            "}\n"
                        ),
                    },
                    {
                        "path": "helpers/wait.ts",
                        "content": (
                            "import type { Page } from '@playwright/test';\n"
                            "export async function waitForBanner(page: Page) {\n"
                            "  await page.getByTestId('banner').waitFor();\n"
                            "}\n"
                        ),
                    },
                    {
                        "path": "fixtures/auth.ts",
                        "content": (
                            "import { test as base } from '@playwright/test';\n"
                            "export const test = base.extend({\n"
                            "  authedPage: async ({ page }, use) => { await use(page); },\n"
                            "});\n"
                        ),
                    },
                    {
                        "path": "hooks/global.ts",
                        "content": (
                            "import { test } from '@playwright/test';\n"
                            "test.beforeEach(async ({ page }) => {\n"
                            "  await page.goto('/');\n"
                            "});\n"
                        ),
                    },
                ],
            }
        ]
    )
    components = collect_reusable_components(
        evidence, extractors=(PlaywrightSpecExtractor(),)
    )
    by_kind = {c.kind: c for c in components}
    assert set(by_kind) == {"page_object", "helper", "fixture", "hook"}
    assert by_kind["page_object"].signature
    assert by_kind["helper"].path == "helpers/wait.ts"


def test_a0_e2e_still_detects_playwright_via_default_registry() -> None:
    profile = aggregate_profile(a0_evidence(), default_detector_registry())
    e2e = next(c for c in profile.components if c.label == "oie-e2e")
    assert e2e.facet_status["test_frameworks"] == "detected"
    assert any(f.framework_id == "playwright" for f in e2e.facts)


def test_a0_cancel_spec_extracted_as_test_spec() -> None:
    from test.packs.software_delivery.project_profile.conftest import (
        evidence_for_components,
    )

    evidence = evidence_for_components({"oie-e2e": "acme/oie-e2e"})
    components = collect_reusable_components(
        evidence, extractors=(PlaywrightSpecExtractor(),)
    )
    specs = [c for c in components if c.kind == "test_spec"]
    assert any(c.path.endswith("cancel-order.spec.ts") for c in specs)
    assert not any(c.kind == "page_object" for c in components)
