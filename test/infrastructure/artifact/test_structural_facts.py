"""structural_facts_for maps connector extras into classification facts."""

from __future__ import annotations

from domain.knowledge import SourceDocument, SourceMetadata, SourceReference, SourceType
from infrastructure.artifact.structural_facts import structural_facts_for


def test_jira_issue_type_becomes_provider_type_field() -> None:
    document = SourceDocument(
        SourceMetadata(
            SourceReference("cloud/PROJ:PROJ-1", SourceType.JIRA),
            title="Login",
            extra={"jira_issue_type": "Story", "jira_issue_key": "PROJ-1"},
        ),
        "body",
    )

    facts = structural_facts_for(document)

    assert facts.provider_type_field == "Story"
    assert facts.path == ""
    assert facts.association_roles == ()


def test_github_path_and_roles() -> None:
    document = SourceDocument(
        SourceMetadata(
            SourceReference("acme/repo:tests/test_login.py", SourceType.GITHUB),
            title="test_login.py",
            extra={
                "github_path": "tests/test_login.py",
                "association_roles": "backend,testing",
            },
        ),
        "assert True",
    )

    facts = structural_facts_for(document)

    assert facts.path == "tests/test_login.py"
    assert facts.filename == "test_login.py"
    assert facts.association_roles == ("backend", "testing")
