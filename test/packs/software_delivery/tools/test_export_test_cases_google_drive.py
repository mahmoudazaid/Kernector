"""Tests for software_delivery.export_test_cases_google_drive tool adapter."""

from __future__ import annotations

import json
from collections.abc import Sequence

import pytest

from domain.artifacts import Artifact, ArtifactReceipt
from domain.errors import ConnectorAuthError, ConnectorError, ToolFailureError
from packs.software_delivery.errors import GoogleDriveExportValidationError
from packs.software_delivery.limits import (
    DEFAULT_EXPORT_FILE_NAME,
    MAX_EXPORT_ARTIFACT_BYTES,
    MAX_EXPORT_DOCUMENT_TITLE_CHARS,
    MAX_EXPORT_FILE_NAME_CHARS,
    MAX_EXPORT_TITLE_CHARS,
    MAX_EXPORT_TITLES,
)
from packs.software_delivery.tools.export_test_cases_google_drive import (
    TOOL_NAME,
    ExportTestCasesGoogleDriveTool,
)


class _FakeUploader:
    def __init__(self) -> None:
        self.calls: list[tuple[Artifact, str]] = []
        self.error: Exception | None = None
        self.receipt = ArtifactReceipt(artifact_id="file-9", file_name="out.md")

    def upload(self, artifact: Artifact, *, parent_id: str) -> ArtifactReceipt:
        self.calls.append((artifact, parent_id))
        if self.error is not None:
            raise self.error
        return ArtifactReceipt(
            artifact_id=self.receipt.artifact_id,
            file_name=artifact.file_name,
        )


def _valid_arguments(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "document_title": "Issue 482",
        "titles": ["Login with MFA", "Checkout fails"],
        "folder_id": "folderExport123",
    }
    args.update(overrides)
    return args


def _tool(
    *,
    render_calls: list[tuple[str, tuple[str, ...]]] | None = None,
    markdown: str = "# Issue 482\n\n## Selected tests\n\n- Login with MFA\n",
    uploader: _FakeUploader | None = None,
    render_error: Exception | None = None,
) -> tuple[ExportTestCasesGoogleDriveTool, _FakeUploader]:
    calls = render_calls if render_calls is not None else []
    fake = uploader if uploader is not None else _FakeUploader()

    def render(document_title: str, titles: Sequence[str]) -> str:
        calls.append((document_title, tuple(titles)))
        if render_error is not None:
            raise render_error
        return markdown

    return ExportTestCasesGoogleDriveTool(render=render, uploader=fake), fake


def test_tool_name_and_description() -> None:
    tool, _ = _tool()
    assert tool.name == TOOL_NAME == "software_delivery.export_test_cases_google_drive"
    assert tool.description.strip()


def test_valid_arguments_render_upload_and_return_safe_receipt() -> None:
    render_calls: list[tuple[str, tuple[str, ...]]] = []
    tool, uploader = _tool(render_calls=render_calls, markdown="# body\n")
    result = tool.run(_valid_arguments(file_name="cases.md"))
    assert json.loads(result) == {"file_id": "file-9", "file_name": "cases.md"}
    assert render_calls == [("Issue 482", ("Login with MFA", "Checkout fails"))]
    assert len(uploader.calls) == 1
    artifact, parent_id = uploader.calls[0]
    assert parent_id == "folderExport123"
    assert artifact.file_name == "cases.md"
    assert artifact.media_type == "text/markdown"
    assert artifact.content == b"# body\n"
    assert "# body" not in result


def test_default_file_name_from_document_title() -> None:
    tool, uploader = _tool()
    tool.run(_valid_arguments(document_title="Issue 482"))
    assert uploader.calls[0][0].file_name == "Issue-482.md"


def test_unsafe_document_title_falls_back_to_default_file_name() -> None:
    tool, uploader = _tool()
    tool.run(_valid_arguments(document_title="***"))
    assert uploader.calls[0][0].file_name == DEFAULT_EXPORT_FILE_NAME


def test_blank_document_title_fails_before_render() -> None:
    render_calls: list[tuple[str, tuple[str, ...]]] = []
    tool, uploader = _tool(render_calls=render_calls)
    with pytest.raises(GoogleDriveExportValidationError, match="document_title"):
        tool.run(_valid_arguments(document_title="   "))
    assert render_calls == []
    assert uploader.calls == []


def test_string_titles_rejected_before_render() -> None:
    render_calls: list[tuple[str, tuple[str, ...]]] = []
    tool, uploader = _tool(render_calls=render_calls)
    with pytest.raises(GoogleDriveExportValidationError, match="titles"):
        tool.run(_valid_arguments(titles="not-a-list"))
    assert render_calls == []
    assert uploader.calls == []


def test_unknown_root_key_rejected() -> None:
    tool, uploader = _tool()
    args = _valid_arguments()
    args["prompt"] = "free form"
    with pytest.raises(GoogleDriveExportValidationError, match="unknown"):
        tool.run(args)
    assert uploader.calls == []


def test_missing_folder_id_rejected() -> None:
    tool, uploader = _tool()
    args = _valid_arguments()
    del args["folder_id"]
    with pytest.raises(GoogleDriveExportValidationError, match="folder_id"):
        tool.run(args)
    assert uploader.calls == []


def test_invalid_folder_id_rejected() -> None:
    tool, uploader = _tool()
    with pytest.raises(GoogleDriveExportValidationError, match="folder_id"):
        tool.run(_valid_arguments(folder_id="not a valid id!"))
    assert uploader.calls == []


def test_empty_titles_rejected() -> None:
    tool, _ = _tool()
    with pytest.raises(GoogleDriveExportValidationError, match="titles"):
        tool.run(_valid_arguments(titles=[]))


def test_too_many_titles_rejected() -> None:
    tool, _ = _tool()
    titles = [f"t{i}" for i in range(MAX_EXPORT_TITLES + 1)]
    with pytest.raises(GoogleDriveExportValidationError, match="titles"):
        tool.run(_valid_arguments(titles=titles))


def test_title_over_limit_rejected() -> None:
    tool, _ = _tool()
    with pytest.raises(GoogleDriveExportValidationError, match="titles\\[0\\]"):
        tool.run(_valid_arguments(titles=["x" * (MAX_EXPORT_TITLE_CHARS + 1)]))


def test_document_title_over_limit_rejected() -> None:
    tool, _ = _tool()
    with pytest.raises(GoogleDriveExportValidationError, match="document_title"):
        tool.run(
            _valid_arguments(
                document_title="x" * (MAX_EXPORT_DOCUMENT_TITLE_CHARS + 1)
            )
        )


@pytest.mark.parametrize(
    "file_name",
    ["../x.md", "a/b.md", "a\\b.md", "bad|name.md", "no-ext", "x.MD", ".", ".."],
)
def test_invalid_file_name_rejected(file_name: str) -> None:
    tool, uploader = _tool()
    with pytest.raises(GoogleDriveExportValidationError, match="file_name"):
        tool.run(_valid_arguments(file_name=file_name))
    assert uploader.calls == []


def test_file_name_over_limit_rejected() -> None:
    tool, _ = _tool()
    name = "a" * (MAX_EXPORT_FILE_NAME_CHARS - 2) + ".md"
    assert len(name) == MAX_EXPORT_FILE_NAME_CHARS + 1
    with pytest.raises(GoogleDriveExportValidationError, match="file_name"):
        tool.run(_valid_arguments(file_name=name))


def test_renderer_failure_becomes_tool_failure_not_validation() -> None:
    tool, uploader = _tool(render_error=ValueError("internal markdown boom"))
    with pytest.raises(ToolFailureError, match="Markdown rendering failed") as raised:
        tool.run(_valid_arguments())
    assert isinstance(raised.value.__cause__, ValueError)
    assert "boom" not in str(raised.value)
    assert uploader.calls == []


def test_oversized_render_output_fails_before_upload() -> None:
    huge = "x" * (MAX_EXPORT_ARTIFACT_BYTES + 1)
    tool, uploader = _tool(markdown=huge)
    with pytest.raises(ToolFailureError):
        tool.run(_valid_arguments())
    assert uploader.calls == []


def test_uploader_auth_error_maps_to_tool_failure() -> None:
    uploader = _FakeUploader()
    uploader.error = ConnectorAuthError("token ya29.secret")
    tool, _ = _tool(uploader=uploader)
    with pytest.raises(ToolFailureError, match="authorization") as raised:
        tool.run(_valid_arguments())
    assert "ya29" not in str(raised.value)
    assert isinstance(raised.value.__cause__, ConnectorAuthError)


def test_uploader_generic_error_maps_to_tool_failure() -> None:
    uploader = _FakeUploader()
    uploader.error = ConnectorError("provider body leaked")
    tool, _ = _tool(uploader=uploader)
    with pytest.raises(ToolFailureError, match="export failed") as raised:
        tool.run(_valid_arguments())
    assert "provider body" not in str(raised.value)
