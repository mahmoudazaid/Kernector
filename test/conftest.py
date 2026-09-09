"""Suite-wide isolation from a developer ``.env`` catalog configuration."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _pin_document_catalog_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point every test at an ephemeral JSON catalog under ``tmp_path``.

    ``load_settings`` calls ``load_dotenv(override=True)``. Without this, the
    first settings load permanently copies a developer's ``.env`` into the
    process. Catalog paths are also pinned so a leftover
    ``DOCUMENT_CATALOG_BACKEND=sql`` cannot point tests at a real file.
    """
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("DOCUMENT_CATALOG_BACKEND", "json")
    monkeypatch.setenv("DOCUMENT_CATALOG_PATH", str(tmp_path / "catalog.json"))
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite")
    )
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "test-workspace")
