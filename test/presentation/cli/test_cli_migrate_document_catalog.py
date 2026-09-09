"""Behavior tests for the document-catalog migration CLI."""

from __future__ import annotations

import pytest

from application.errors import ConfigurationError
from composition.errors import DocumentOperationError
from presentation.cli import migrate_document_catalog as migrate_cli


def test_successful_migration_returns_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(migrate_cli, "load_runtime_settings", lambda: object())
    monkeypatch.setattr(migrate_cli, "migrate_document_catalog", lambda _settings: None)

    code = migrate_cli.main()

    captured = capsys.readouterr()
    assert code == 0
    assert "migrated_document_catalog=ok" in captured.out
    assert captured.err == ""


def test_configuration_failure_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    migrate_calls: list[object] = []

    def _boom() -> object:
        raise ConfigurationError("DOCUMENT_CATALOG_BACKEND must be 'sql'")

    monkeypatch.setattr(migrate_cli, "load_runtime_settings", _boom)
    monkeypatch.setattr(
        migrate_cli,
        "migrate_document_catalog",
        lambda settings: migrate_calls.append(settings),
    )

    code = migrate_cli.main()

    captured = capsys.readouterr()
    assert code == 2
    assert "DOCUMENT_CATALOG_BACKEND must be 'sql'" in captured.err
    assert captured.out == ""
    assert migrate_calls == []


def test_wrapper_configuration_failure_returns_exit_two(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(migrate_cli, "load_runtime_settings", lambda: object())
    monkeypatch.setattr(
        migrate_cli,
        "migrate_document_catalog",
        lambda _settings: (_ for _ in ()).throw(
            ConfigurationError("DOCUMENT_CATALOG_WORKSPACE_ID is required")
        ),
    )

    code = migrate_cli.main()

    captured = capsys.readouterr()
    assert code == 2
    assert "DOCUMENT_CATALOG_WORKSPACE_ID is required" in captured.err
    assert captured.out == ""


def test_import_failure_returns_exit_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(migrate_cli, "load_runtime_settings", lambda: object())
    monkeypatch.setattr(
        migrate_cli,
        "migrate_document_catalog",
        lambda _settings: (_ for _ in ()).throw(
            DocumentOperationError("could not import catalog")
        ),
    )

    code = migrate_cli.main()

    captured = capsys.readouterr()
    assert code == 1
    assert "could not import catalog" in captured.err
    assert captured.out == ""
    assert "Traceback" not in captured.err
