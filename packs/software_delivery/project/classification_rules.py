"""Software Delivery context classification rules (ADR 0011 §10, #373)."""

from __future__ import annotations

from domain.artifact.rules import ContextClassificationRule, ContextRuleMode

SOFTWARE_DELIVERY_CONTEXT_RULES: tuple[ContextClassificationRule, ...] = (
    ContextClassificationRule(
        rule_id="jira_story_bug_to_business",
        context="business",
        mode=ContextRuleMode.REPLACE,
        provider_type_fields=("Story", "Bug", "Requirement", "Epic"),
    ),
    ContextClassificationRule(
        rule_id="jira_test_to_testing",
        context="testing",
        mode=ContextRuleMode.REPLACE,
        provider_type_fields=("Test",),
    ),
    ContextClassificationRule(
        rule_id="openapi_to_api_contract",
        context="api_contract",
        mode=ContextRuleMode.ADD,
        path_globs=("**/openapi.*", "**/swagger.*"),
        filename_globs=("openapi.*", "swagger.*"),
        require_valid_spec_root=True,
    ),
    ContextClassificationRule(
        rule_id="test_paths_to_testing",
        context="testing",
        mode=ContextRuleMode.REPLACE,
        path_globs=(
            "tests/**",
            "test/**",
            "e2e/**",
            "**/resources/**",
            "**/fixtures/**",
        ),
        filename_globs=(
            "test_*.py",
            "*_test.py",
            "*.robot",
            "*.resource",
            "*.spec.ts",
            "conftest.py",
        ),
    ),
    ContextClassificationRule(
        rule_id="docs_to_documentation",
        context="documentation",
        mode=ContextRuleMode.ADD,
        path_globs=("docs/**", "**/docs/**"),
    ),
    ContextClassificationRule(
        rule_id="adr_to_documentation",
        context="documentation",
        mode=ContextRuleMode.ADD,
        path_globs=("docs/adr/**", "**/docs/adr/**"),
    ),
    ContextClassificationRule(
        rule_id="operations_paths",
        context="operations",
        mode=ContextRuleMode.REPLACE,
        path_globs=(
            ".github/workflows/**",
            "deploy/**",
            "infra/**",
            "k8s/**",
            "**/*.tf",
            "**/Dockerfile*",
            "**/Jenkinsfile",
            "**/docker-compose*.yml",
            "**/docker-compose*.yaml",
        ),
        filename_globs=(
            "Dockerfile",
            "Dockerfile.*",
            "Jenkinsfile",
            "docker-compose*.yml",
            "docker-compose*.yaml",
            "*.tf",
        ),
    ),
)
