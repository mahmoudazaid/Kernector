"""Suite-wide isolation from a developer ``.env`` catalog configuration."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _pin_document_catalog_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point every test at an ephemeral JSON catalog under ``tmp_path``.

    ``load_settings`` calls ``load_dotenv(override=True)``, so a prior test
    that loaded ``.env`` can leave ``DOCUMENT_CATALOG_BACKEND=sql`` and a
    real sqlite path in ``os.environ``. Re-pinning per test keeps Hub and
    catalog tests off that file.
    """
    monkeypatch.setenv("DOCUMENT_CATALOG_BACKEND", "json")
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_PATH", str(tmp_path / "catalog.json")
    )
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite")
    )
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "test-workspace")
