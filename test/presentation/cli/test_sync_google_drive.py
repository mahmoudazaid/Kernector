"""Behavior tests for the Google Drive sync CLI."""

from __future__ import annotations

import logging

import pytest

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from application.errors import ConfigurationError
from composition import ConnectorSyncError
from presentation.cli import sync_google_drive as sync_cli
from test.log_record import flatten_log_record

SECRET = "DRIVE-SECRET-TOKEN-LEAK"


def _response(*outcomes: ConnectorSyncOutcome) -> ConnectorSyncResponse:
    return ConnectorSyncResponse(outcomes=outcomes)


def _patch(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: ConnectorSyncResponse | None = None,
    error: Exception | None = None,
) -> None:
    monkeypatch.setattr(sync_cli, "load_runtime_settings", lambda: object())
    if error is not None:
        monkeypatch.setattr(
            sync_cli,
            "sync_google_drive",
            lambda _settings: (_ for _ in ()).throw(error),
        )
        return

    assert response is not None
    monkeypatch.setattr(sync_cli, "sync_google_drive", lambda _settings: response)


def test_all_ingested_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(
        monkeypatch,
        response=_response(
            ConnectorSyncOutcome("a", ConnectorSyncStatus.INGESTED, 2),
            ConnectorSyncOutcome("b", ConnectorSyncStatus.INGESTED, 1),
        ),
    )
    code = sync_cli.main()
    captured = capsys.readouterr()
    assert code == 0
    assert "ingested=2" in captured.out
    assert "skipped=0" in captured.out
    assert "failed=0" in captured.out
    assert captured.err == ""
    assert SECRET not in captured.out


def test_all_skipped_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(
        monkeypatch,
        response=_response(
            ConnectorSyncOutcome("a", ConnectorSyncStatus.SKIPPED, 3),
        ),
    )
    code = sync_cli.main()
    captured = capsys.readouterr()
    assert code == 0
    assert "ingested=0" in captured.out
    assert "skipped=1" in captured.out
    assert "failed=0" in captured.out


def test_empty_folder_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, response=_response())
    code = sync_cli.main()
    captured = capsys.readouterr()
    assert code == 0
    assert "ingested=0" in captured.out
    assert "skipped=0" in captured.out
    assert "failed=0" in captured.out


def test_partial_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(
        monkeypatch,
        response=_response(
            ConnectorSyncOutcome("ok", ConnectorSyncStatus.INGESTED, 1),
            ConnectorSyncOutcome(
                "bad", ConnectorSyncStatus.FAILED, 0, error_type="ConnectorError"
            ),
        ),
    )
    code = sync_cli.main()
    captured = capsys.readouterr()
    assert code == 1
    assert "ingested=1" in captured.out
    assert "failed=1" in captured.out
    assert "failed source_id=bad error_type=ConnectorError" in captured.err
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_store_failure_returns_one_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, error=RuntimeError(f"chroma path {SECRET}"))
    code = sync_cli.main()
    captured = capsys.readouterr()
    assert code == 1
    assert "The Google Drive connector sync failed." in captured.err
    assert "Traceback" not in captured.err
    assert SECRET not in captured.err
    assert captured.out == ""


def test_run_level_connector_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, error=ConnectorSyncError("The Google Drive connector sync failed."))
    code = sync_cli.main()
    captured = capsys.readouterr()
    assert code == 1
    assert "The Google Drive connector sync failed." in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err
    assert SECRET not in captured.err


def test_configuration_failure_returns_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(
        monkeypatch,
        error=ConfigurationError("Google Drive connector configuration is invalid."),
    )
    code = sync_cli.main()
    captured = capsys.readouterr()
    assert code == 2
    assert "configuration is invalid" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err


def test_secret_marker_never_appears_in_output_or_logs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    _patch(
        monkeypatch,
        response=_response(
            ConnectorSyncOutcome(
                "bad", ConnectorSyncStatus.FAILED, 0, error_type="ConnectorAuthError"
            )
        ),
    )
    with caplog.at_level(logging.DEBUG):
        code = sync_cli.main()
    captured = capsys.readouterr()
    log_text = "\n".join(flatten_log_record(record) for record in caplog.records)
    assert code == 1
    assert SECRET not in captured.out
    assert SECRET not in captured.err
    assert SECRET not in log_text
    assert SECRET not in caplog.text
    assert "failed source_id=bad error_type=ConnectorAuthError" in captured.err
