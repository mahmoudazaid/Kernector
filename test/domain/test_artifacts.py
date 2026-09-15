"""Unit tests for outbound artifact domain contracts."""

import pytest

from domain.artifacts import Artifact, ArtifactReceipt
from domain.errors import DomainValidationError
from domain.ports import ArtifactUploader

BLANK = ["", "   ", "\n"]


def test_valid_artifact_is_accepted() -> None:
    artifact = Artifact(
        file_name="cases.md",
        media_type="text/markdown",
        content=b"# Title\n",
    )
    assert artifact.file_name == "cases.md"
    assert artifact.media_type == "text/markdown"
    assert artifact.content == b"# Title\n"


@pytest.mark.parametrize("blank", BLANK)
def test_artifact_rejects_blank_file_name(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="file_name"):
        Artifact(file_name=blank, media_type="text/markdown", content=b"x")


@pytest.mark.parametrize("blank", BLANK)
def test_artifact_rejects_blank_media_type(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="media_type"):
        Artifact(file_name="cases.md", media_type=blank, content=b"x")


def test_artifact_rejects_non_bytes_content() -> None:
    with pytest.raises(DomainValidationError, match="content"):
        Artifact(
            file_name="cases.md",
            media_type="text/markdown",
            content="not-bytes",  # type: ignore[arg-type]
        )


def test_valid_artifact_receipt_is_accepted() -> None:
    receipt = ArtifactReceipt(artifact_id="drive-1", file_name="cases.md")
    assert receipt.artifact_id == "drive-1"
    assert receipt.file_name == "cases.md"


@pytest.mark.parametrize("blank", BLANK)
def test_receipt_rejects_blank_artifact_id(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="artifact_id"):
        ArtifactReceipt(artifact_id=blank, file_name="cases.md")


@pytest.mark.parametrize("blank", BLANK)
def test_receipt_rejects_blank_file_name(blank: str) -> None:
    with pytest.raises(DomainValidationError, match="file_name"):
        ArtifactReceipt(artifact_id="drive-1", file_name=blank)


def test_artifact_uploader_accepts_structural_implementation() -> None:
    class _Fake:
        def upload(self, artifact: Artifact, *, parent_id: str) -> ArtifactReceipt:
            assert parent_id == "parent-1"
            return ArtifactReceipt(
                artifact_id="id-1",
                file_name=artifact.file_name,
            )

    uploader: ArtifactUploader = _Fake()
    receipt = uploader.upload(
        Artifact(
            file_name="out.md",
            media_type="text/markdown",
            content=b"x",
        ),
        parent_id="parent-1",
    )
    assert receipt.artifact_id == "id-1"
    assert receipt.file_name == "out.md"
