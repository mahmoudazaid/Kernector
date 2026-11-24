"""Provider kind mapping stays in infrastructure (#373)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
JIRA_EXTRACTOR = (
    REPO_ROOT / "infrastructure" / "connectors" / "jira" / "artifact_extractor.py"
)
APPLICATION_ARTIFACT = REPO_ROOT / "application" / "artifact"
DOMAIN_ARTIFACT = REPO_ROOT / "domain" / "artifact"


def test_jira_default_kind_map_lives_in_infrastructure() -> None:
    text = JIRA_EXTRACTOR.read_text(encoding="utf-8")
    assert "DEFAULT_JIRA_KIND_MAP" in text
    assert '"Story"' in text or "'Story'" in text


def test_application_and_domain_artifact_have_no_jira_issue_type_map() -> None:
    for root in (APPLICATION_ARTIFACT, DOMAIN_ARTIFACT):
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "DEFAULT_JIRA_KIND_MAP" not in text
            assert "issuetype" not in text
