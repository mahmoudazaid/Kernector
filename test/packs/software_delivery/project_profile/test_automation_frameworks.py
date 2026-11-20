"""Automation framework detectors (#429 slices 3–8)."""

from __future__ import annotations

from packs.software_delivery.project_profile.adapters import CucumberStepReusableSource
from packs.software_delivery.project_profile.detectors import default_detector_registry
from packs.software_delivery.project_profile.extractors.cypress_support import (
    CypressSupportExtractor,
)
from packs.software_delivery.project_profile.extractors.selenium_pages import (
    SeleniumPageExtractor,
)
from packs.software_delivery.project_profile.intake import ingest_profile_evidence
from packs.software_delivery.project_profile.models import LineRange, ReusableComponent
from packs.software_delivery.project_profile.registry import aggregate_profile
from packs.software_delivery.project_profile.reusable import collect_reusable_components
from packs.software_delivery.project_profile.service import profile_project


def _ids(component) -> set[str | None]:
    return {
        f.framework_id
        for f in component.facts
        if f.facet == "test_frameworks"
    }


def test_cypress_detects_config_and_support_helpers() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "ui",
                "files": [
                    {
                        "path": "package.json",
                        "content": '{"devDependencies":{"cypress":"13.0.0"}}\n',
                    },
                    {
                        "path": "cypress.config.ts",
                        "content": "export default { e2e: { baseUrl: 'http://localhost' } }\n",
                    },
                    {
                        "path": "cypress/support/commands.ts",
                        "content": (
                            "Cypress.Commands.add('login', () => {\n"
                            "  cy.visit('/login');\n"
                            "});\n"
                        ),
                    },
                    {
                        "path": "cypress/fixtures/user.json",
                        "content": '{"email":"a@b.c"}\n',
                    },
                    {
                        "path": "cypress/support/empty.ts",
                        "content": "// no commands\n",
                    },
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert "cypress" in _ids(component)
    assert any(c.name == "test_root" for c in component.conventions)
    assert any(
        c.name == "framework_version" and c.value == "cypress==13.0.0"
        for c in component.conventions
    )
    components, diagnostics = collect_reusable_components(
        evidence, extractors=(CypressSupportExtractor(),), return_diagnostics=True
    )
    kinds = {c.kind for c in components}
    assert "helper" in kinds
    assert "fixture" in kinds
    assert any("insufficient" in d.lower() for d in diagnostics)


def test_selenium_direct_python_and_page_object() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "web",
                "files": [
                    {"path": "requirements.txt", "content": "selenium==4.15.0\n"},
                    {
                        "path": "pages/login_page.py",
                        "content": (
                            "from selenium.webdriver.common.by import By\n"
                            "class LoginPage:\n"
                            "    def __init__(self, driver):\n"
                            "        self.driver = driver\n"
                            "    def open(self):\n"
                            "        self.driver.find_element(By.ID, 'user')\n"
                        ),
                    },
                    {
                        "path": "pages/empty_page.py",
                        "content": "# placeholder\n",
                    },
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert "selenium" in _ids(component)
    assert any(
        c.name == "framework_version" and c.value == "selenium==4.15.0"
        for c in component.conventions
    )
    components, diagnostics = collect_reusable_components(
        evidence, extractors=(SeleniumPageExtractor(),), return_diagnostics=True
    )
    assert any(c.kind == "page_object" and c.signature == "LoginPage" for c in components)
    assert any("insufficient" in d.lower() for d in diagnostics)


def test_selenium_plus_pytest_coexist() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "web",
                "files": [
                    {
                        "path": "requirements.txt",
                        "content": "selenium==4.15.0\npytest==8.3.0\n",
                    }
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert _ids(component) == {"selenium", "pytest"}
    assert component.facet_status["test_frameworks"] == "detected"


def test_junit_exact_version_and_property_omitted() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "java",
                "files": [
                    {
                        "path": "pom.xml",
                        "content": (
                            "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">"
                            "<dependencies>"
                            "<dependency>"
                            "<groupId>org.junit.jupiter</groupId>"
                            "<artifactId>junit-jupiter</artifactId>"
                            "<version>5.10.0</version>"
                            "</dependency>"
                            "</dependencies>"
                            "</project>\n"
                        ),
                    }
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert "junit" in _ids(component)
    assert any(c.value == "junit==5.10.0" for c in component.conventions)

    evidence2 = ingest_profile_evidence(
        [
            {
                "component": "java",
                "files": [
                    {
                        "path": "pom.xml",
                        "content": (
                            "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">"
                            "<dependencies>"
                            "<dependency>"
                            "<groupId>org.junit.jupiter</groupId>"
                            "<artifactId>junit-jupiter</artifactId>"
                            "<version>${junit.version}</version>"
                            "</dependency>"
                            "</dependencies>"
                            "</project>\n"
                        ),
                    }
                ],
            }
        ]
    )
    profile2 = aggregate_profile(evidence2, default_detector_registry())
    assert "junit" in _ids(profile2.components[0])
    assert not any(
        c.name == "framework_version" for c in profile2.components[0].conventions
    )


def test_junit_testng_deps_only_ambiguous() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "java",
                "files": [
                    {
                        "path": "pom.xml",
                        "content": (
                            "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">"
                            "<dependencies>"
                            "<dependency>"
                            "<groupId>org.junit.jupiter</groupId>"
                            "<artifactId>junit-jupiter</artifactId>"
                            "<version>5.10.0</version>"
                            "</dependency>"
                            "<dependency>"
                            "<groupId>org.testng</groupId>"
                            "<artifactId>testng</artifactId>"
                            "<version>7.8.0</version>"
                            "</dependency>"
                            "</dependencies>"
                            "</project>\n"
                        ),
                    }
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert _ids(component) == {"junit", "testng"}
    assert component.facet_status["test_frameworks"] == "ambiguous"


def test_junit_testng_with_independent_ownership_detected() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "java",
                "files": [
                    {
                        "path": "pom.xml",
                        "content": (
                            "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">"
                            "<dependencies>"
                            "<dependency>"
                            "<groupId>org.junit.jupiter</groupId>"
                            "<artifactId>junit-jupiter</artifactId>"
                            "<version>5.10.0</version>"
                            "</dependency>"
                            "<dependency>"
                            "<groupId>org.testng</groupId>"
                            "<artifactId>testng</artifactId>"
                            "<version>7.8.0</version>"
                            "</dependency>"
                            "</dependencies>"
                            "</project>\n"
                        ),
                    },
                    {
                        "path": "src/test/java/DemoTest.java",
                        "content": "import org.junit.jupiter.api.Test;\nclass DemoTest {}\n",
                    },
                    {
                        "path": "testng.xml",
                        "content": "<!DOCTYPE suite SYSTEM \"https://testng.org/testng-1.0.dtd\">"
                        "<suite name=\"All\"><test name=\"t\"/></suite>\n",
                    },
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert _ids(component) == {"junit", "testng"}
    assert component.facet_status["test_frameworks"] == "detected"


def test_appium_and_direct_selenium_coexist() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "mobile",
                "files": [
                    {
                        "path": "requirements.txt",
                        "content": (
                            "Appium-Python-Client==3.1.0\n"
                            "selenium==4.15.0\n"
                        ),
                    }
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert _ids(component) == {"appium", "selenium"}
    assert component.facet_status["test_frameworks"] == "detected"


def test_appium_alone_does_not_invent_selenium() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "mobile",
                "files": [
                    {
                        "path": "requirements.txt",
                        "content": "Appium-Python-Client==3.1.0\n",
                    }
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    assert _ids(profile.components[0]) == {"appium"}


def test_cucumber_plus_junit_detected_gherkin_separate() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "bdd",
                "files": [
                    {
                        "path": "pom.xml",
                        "content": (
                            "<project xmlns=\"http://maven.apache.org/POM/4.0.0\">"
                            "<dependencies>"
                            "<dependency>"
                            "<groupId>io.cucumber</groupId>"
                            "<artifactId>cucumber-java</artifactId>"
                            "<version>7.14.0</version>"
                            "</dependency>"
                            "<dependency>"
                            "<groupId>org.junit.jupiter</groupId>"
                            "<artifactId>junit-jupiter</artifactId>"
                            "<version>5.10.0</version>"
                            "</dependency>"
                            "</dependencies>"
                            "</project>\n"
                        ),
                    },
                    {
                        "path": "features/login.feature",
                        "content": "Feature: Login\n  Scenario: ok\n    Given I am on login\n",
                    },
                    {
                        "path": "features/steps/login_steps.java",
                        "content": "// glue placeholder — steps come from #298\n",
                    },
                ],
            }
        ]
    )
    profile = aggregate_profile(evidence, default_detector_registry())
    component = profile.components[0]
    assert "cucumber" in _ids(component)
    assert "junit" in _ids(component)
    assert component.facet_status["test_frameworks"] == "detected"
    assert any(
        f.facet == "specification_syntaxes" and f.value == "gherkin"
        for f in component.facts
    )
    assert not any(
        c.kind == "step_definition" for c in component.reusable_components
    )


def test_cucumber_steps_only_from_source_adapter() -> None:
    evidence = ingest_profile_evidence(
        [
            {
                "component": "bdd",
                "files": [
                    {
                        "path": "package.json",
                        "content": '{"devDependencies":{"@cucumber/cucumber":"10.0.0"}}\n',
                    }
                ],
            }
        ]
    )
    step = ReusableComponent(
        component_id="step:login",
        kind="step_definition",
        framework_id="cucumber",
        signature="I am on login",
        path="features/steps/login.js",
        content_hash="abc",
        line_range=LineRange(1, 3),
        documentation="from catalogue",
    )

    class Catalogue:
        def list_step_definitions(self, evidence_payload):
            return (step,)

    empty = CucumberStepReusableSource()
    assert empty.list_components(evidence) == ()

    wired = CucumberStepReusableSource(Catalogue())
    profile = profile_project(
        [
            {
                "component": "bdd",
                "files": [
                    {
                        "path": "package.json",
                        "content": '{"devDependencies":{"@cucumber/cucumber":"10.0.0"}}\n',
                    }
                ],
            }
        ],
        sources=(wired,),
    )
    assert any(c.kind == "step_definition" for c in profile.reusable_components)
    assert all(
        c.kind != "step_definition" or c.signature == "I am on login"
        for c in profile.reusable_components
    )
