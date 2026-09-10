"""load_dotenv precedence is not stubbed away by the suite-wide fixture."""

from __future__ import annotations

from pathlib import Path

import pytest
from dotenv import load_dotenv as real_load_dotenv

from infrastructure.config import load_settings


def test_dotenv_does_not_override_process_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process env wins over `.env` when ``override=False`` (python-dotenv default)."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "DOCUMENT_CATALOG_WORKSPACE_ID=local\n"
        "OPENROUTER_API_KEY=\n"
        "HTTP_DEV_CORS=true\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "production")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-REAL-KEY")
    monkeypatch.setenv("HTTP_DEV_CORS", "false")
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite")
    )
    monkeypatch.delenv("DOCUMENT_CATALOG_BACKEND", raising=False)
    monkeypatch.delenv("DOCUMENT_CATALOG_PATH", raising=False)
    # Restore the real loader; suite conftest stubs it for isolation.
    monkeypatch.setattr("infrastructure.config.load_dotenv", real_load_dotenv)

    settings = load_settings()
    assert settings.document_catalog.workspace_id == "production"
    assert settings.openrouter.api_key == "sk-or-REAL-KEY"
    assert settings.http.dev_cors is False
