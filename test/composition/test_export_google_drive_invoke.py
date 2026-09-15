"""InvokeTool opacity for Google Drive export registration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from application.contracts import InvokeToolRequest
from application.invoke_tool import InvokeTool, ToolRegistry
from domain.artifacts import Artifact, ArtifactReceipt
from domain.errors import ToolArgumentValidationError, ToolFailureError
from infrastructure.config import load_settings
from packs.software_delivery.tools.export_test_cases_google_drive import (
    TOOL_NAME,
    ExportTestCasesGoogleDriveTool,
)


class _Uploader:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[Artifact, str]] = []

    def upload(self, artifact: Artifact, *, parent_id: str) -> ArtifactReceipt:
        self.calls.append((artifact, parent_id))
        if self.fail:
            raise ToolFailureError("upload blocked")
        return ArtifactReceipt(artifact_id="drive-99", file_name=artifact.file_name)


def test_invoke_tool_returns_opaque_receipt_json() -> None:
    tool = ExportTestCasesGoogleDriveTool(
        render=lambda title, titles: f"# {title}\n",
        uploader=_Uploader(),
    )
    invoke = InvokeTool(ToolRegistry([tool]))
    response = invoke.execute(
        InvokeToolRequest(
            TOOL_NAME,
            {
                "document_title": "Issue 482",
                "titles": ["Login with MFA"],
                "folder_id": "folderExport123",
            },
        )
    )
    assert response.tool_name == TOOL_NAME
    assert json.loads(response.result) == {
        "file_id": "drive-99",
        "file_name": "Issue-482.md",
    }


def test_invoke_tool_propagates_validation_error() -> None:
    tool = ExportTestCasesGoogleDriveTool(
        render=lambda *_a: "#\n",
        uploader=_Uploader(),
    )
    invoke = InvokeTool(ToolRegistry([tool]))
    with pytest.raises(ToolArgumentValidationError):
        invoke.execute(
            InvokeToolRequest(
                TOOL_NAME,
                {
                    "document_title": "x",
                    "titles": [],
                    "folder_id": "folderExport123",
                },
            )
        )


def test_invoke_tool_propagates_tool_failure() -> None:
    tool = ExportTestCasesGoogleDriveTool(
        render=lambda *_a: "#\n",
        uploader=_Uploader(fail=True),
    )
    invoke = InvokeTool(ToolRegistry([tool]))
    with pytest.raises(ToolFailureError, match="upload blocked"):
        invoke.execute(
            InvokeToolRequest(
                TOOL_NAME,
                {
                    "document_title": "Issue",
                    "titles": ["A"],
                    "folder_id": "folderExport123",
                },
            )
        )


def test_build_invoke_tool_registers_export_when_oauth_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from composition.container import build_invoke_tool

    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    monkeypatch.delenv("GOOGLE_DRIVE_EXPORT_FOLDER_ID", raising=False)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client.apps.googleusercontent.com")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "secret")
    monkeypatch.setenv(
        "GOOGLE_OAUTH_REDIRECT_URI",
        "http://127.0.0.1:8000/api/v1/connectors/google-drive/oauth/callback",
    )
    monkeypatch.setenv(
        "GOOGLE_OAUTH_TOKEN_PATH", str(tmp_path / "google-oauth-connection.json")
    )
    monkeypatch.setenv(
        "GOOGLE_OAUTH_STATE_PATH", str(tmp_path / "google-oauth-state.json")
    )
    settings = load_settings()
    invoke = build_invoke_tool(settings)
    assert TOOL_NAME in invoke._registry  # noqa: SLF001 — registry seam for wiring


def test_build_invoke_tool_omits_export_without_oauth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from composition.container import build_invoke_tool

    monkeypatch.setenv("DOMAIN_TOOL_PACKS", "software-delivery")
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GOOGLE_OAUTH_REDIRECT_URI", raising=False)
    settings = load_settings()
    invoke = build_invoke_tool(settings)
    assert TOOL_NAME not in invoke._registry  # noqa: SLF001
