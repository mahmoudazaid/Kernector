"""Suite-wide isolation from a developer ``.env`` catalog configuration."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings_from_dotenv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stop ``load_settings`` from copying a developer ``.env`` into ``os.environ``.

    ``load_settings`` calls ``load_dotenv(override=False)``. Catalog paths are
    also pinned under ``tmp_path`` so tests never touch ``data/catalog``.
    """
    monkeypatch.setattr("infrastructure.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv(
        "DOCUMENT_CATALOG_SQL_PATH", str(tmp_path / "catalog.sqlite")
    )
    monkeypatch.setenv("DOCUMENT_CATALOG_WORKSPACE_ID", "test-workspace")
    monkeypatch.setenv("DOCUMENT_UPLOAD_BLOB_PATH", str(tmp_path / "upload-blobs"))
    monkeypatch.delenv("DOCUMENT_CATALOG_BACKEND", raising=False)
    monkeypatch.delenv("DOCUMENT_CATALOG_PATH", raising=False)
