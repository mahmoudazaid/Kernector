"""Behavior tests for the GitHub sync CLI."""

from __future__ import annotations

import pytest

from application.contracts import (
    ConnectorSyncOutcome,
    ConnectorSyncResponse,
    ConnectorSyncStatus,
)
from application.errors import ConfigurationError
from composition import ConnectorSyncError
from presentation.cli import sync_github as sync_cli

SECRET = "GITHUB-SECRET-TOKEN-LEAK"


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
            "sync_github",
            lambda _settings: (_ for _ in ()).throw(error),
        )
        return
    assert response is not None
    monkeypatch.setattr(sync_cli, "sync_github", lambda _settings: response)


def test_prints_discovered_and_updated_counts(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(
        monkeypatch,
        response=_response(
            ConnectorSyncOutcome("a", ConnectorSyncStatus.INGESTED, 2),
            ConnectorSyncOutcome("b", ConnectorSyncStatus.UPDATED, 1),
            ConnectorSyncOutcome("c", ConnectorSyncStatus.SKIPPED, 3),
            ConnectorSyncOutcome("d", ConnectorSyncStatus.REMOVED, 0),
        ),
    )
    code = sync_cli.main()
    captured = capsys.readouterr()
    assert code == 0
    assert "discovered=3" in captured.out
    assert "ingested=1" in captured.out
    assert "updated=1" in captured.out
    assert "skipped=1" in captured.out
    assert "removed=1" in captured.out
    assert "failed=0" in captured.out
    assert SECRET not in captured.out


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
    assert "failed=1" in captured.out
    assert "failed source_id=bad error_type=ConnectorError" in captured.err
    assert SECRET not in captured.err


def test_run_level_failure_returns_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(monkeypatch, error=ConnectorSyncError("The GitHub connector sync failed."))
    assert sync_cli.main() == 1
    assert "The GitHub connector sync failed." in capsys.readouterr().err


def test_configuration_failure_returns_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch(
        monkeypatch,
        error=ConfigurationError("GitHub connector configuration is invalid."),
    )
    assert sync_cli.main() == 2
    assert "configuration is invalid" in capsys.readouterr().err
