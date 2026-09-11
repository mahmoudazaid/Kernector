"""load_dotenv precedence is not stubbed away by the suite-wide fixture."""

from __future__ import annotations

import functools
from pathlib import Path

import pytest
from dotenv import load_dotenv as real_load_dotenv

from infrastructure.config import load_settings


def _pin_dotenv(monkeypatch: pytest.MonkeyPatch, env_file: Path) -> None:
    """Load only ``env_file`` so ``override=`` in ``load_settings`` is under test."""
    monkeypatch.setattr(
        "infrastructure.config.load_dotenv",
        functools.partial(real_load_dotenv, env_file),
    )


def test_dotenv_does_not_override_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process env wins over `.env` when ``override=False``."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DOCUMENT_CATALOG_WORKSPACE_ID=local\n"
        "OPENROUTER_API_KEY=\n"
        "HTTP_DEV_CORS=true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "production")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-REAL-KEY")
    monkeypatch.setenv("HTTP_DEV_CORS", "false")
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite")
    )
    monkeypatch.delenv("DOCUMENT_CATALOG_BACKEND", raising=False)
    monkeypatch.delenv("DOCUMENT_CATALOG_PATH", raising=False)
    _pin_dotenv(monkeypatch, env_file)

    settings = load_settings()
    assert settings.document_catalog.workspace_id == "production"
    assert settings.openrouter.api_key == "sk-or-REAL-KEY"
    assert settings.http.dev_cors is False


def test_dotenv_supplies_absent_process_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unset keys are filled from `.env` when ``override=False``."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DOCUMENT_CATALOG_WORKSPACE_ID=local\n"
        "HTTP_CORS_ORIGINS=http://localhost:3000\n",
        encoding="utf-8",
    )
    # setenv then delenv so monkeypatch records undo even when the key
    # was absent (bare delenv records nothing for missing keys).
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "")
    monkeypatch.delenv("DOCUMENT_CATALOG_WORKSPACE_ID")
    monkeypatch.setenv("HTTP_CORS_ORIGINS", "")
    monkeypatch.delenv("HTTP_CORS_ORIGINS")
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite")
    )
    monkeypatch.delenv("DOCUMENT_CATALOG_BACKEND", raising=False)
    monkeypatch.delenv("DOCUMENT_CATALOG_PATH", raising=False)
    _pin_dotenv(monkeypatch, env_file)

    settings = load_settings()
    assert settings.document_catalog.workspace_id == "local"
    assert settings.http.cors_origins == ("http://localhost:3000",)
