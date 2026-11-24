"""GitHub artifact descriptor extractors (#373)."""

from __future__ import annotations

from domain.artifact.kinds import ArtifactKind
from domain.knowledge import SourceDocument, SourceMetadata, SourceReference, SourceType
from infrastructure.connectors.github.artifact_extractor import (
    GitHubArtifactDescriptorExtractor,
)


def _file_document(
    path: str,
    *,
    roles: str = "",
    owner: str = "acme",
    repo: str = "proj-orders",
) -> SourceDocument:
    extra = {
        "github_owner": owner,
        "github_repo": repo,
        "github_path": path,
        "github_blob_sha": "sha-file",
        "github_url": f"https://github.com/{owner}/{repo}/blob/main/{path}",
        "file_name": path.rsplit("/", 1)[-1],
    }
    if roles:
        extra["association_roles"] = roles
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference(f"{owner}/{repo}:{path}", SourceType.GITHUB),
            title=path.rsplit("/", 1)[-1],
            provider="github",
            content_format="text",
            extra=extra,
        ),
        "print('ok')\n",
    )


def _issue_document(
    *,
    owner: str = "acme",
    repo: str = "proj-orders",
    number: int = 42,
) -> SourceDocument:
    return SourceDocument(
        SourceMetadata(
            reference=SourceReference("issue:node-1", SourceType.GITHUB),
            title="Cancel fails for paid orders",
            provider="github",
            content_format="markdown",
            extra={
                "github_issue_number": str(number),
                "github_repository": f"{owner}/{repo}",
                "github_issue_url": f"https://github.com/{owner}/{repo}/issues/{number}",
                "github_updated_at": "2026-02-01T00:00:00Z",
                "file_name": f"issue-{number}.md",
            },
        ),
        "# issue\n",
    )


def test_repo_file_defaults_to_code_file() -> None:
    extractor = GitHubArtifactDescriptorExtractor()

    descriptor = extractor.describe(_file_document("orders/cancel.py"))

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.CODE_FILE
    assert descriptor.external_keys == ()
    assert descriptor.revision == "sha-file"


def test_testing_role_marks_automated_test() -> None:
    extractor = GitHubArtifactDescriptorExtractor()

    descriptor = extractor.describe(
        _file_document("orders/cancel.py", roles="testing")
    )

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.AUTOMATED_TEST


def test_test_glob_marks_automated_test() -> None:
    extractor = GitHubArtifactDescriptorExtractor()

    descriptor = extractor.describe(
        _file_document("tests/orders/cancel_order.robot")
    )

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.AUTOMATED_TEST


def test_test_support_globs() -> None:
    extractor = GitHubArtifactDescriptorExtractor()

    descriptor = extractor.describe(
        _file_document("resources/orders.resource")
    )

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.TEST_SUPPORT


def test_github_issue_is_work_item_with_owner_repo_number_key() -> None:
    extractor = GitHubArtifactDescriptorExtractor()

    descriptor = extractor.describe(_issue_document(number=7))

    assert descriptor is not None
    assert descriptor.kind == ArtifactKind.WORK_ITEM
    assert descriptor.external_keys == ("acme/proj-orders#7",)
    assert descriptor.revision == "2026-02-01T00:00:00Z"
