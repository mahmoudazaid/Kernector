"""CLI seam for pre-traffic SQLite migrate (#486)."""

from __future__ import annotations

from pathlib import Path

from composition.sqlite_migrate import MigrateSqliteError, MigrateSqliteResult
from presentation.cli.migrate_sqlite import main


def test_cli_prints_ok_and_returns_zero(tmp_path: Path) -> None:
    result = MigrateSqliteResult(
        catalog_path=tmp_path / "catalog.sqlite",
        auth_path=tmp_path / "auth.sqlite",
        workspace_store_path=tmp_path / "workspace.sqlite",
        feedback_path=tmp_path / "feedback.sqlite",
        backups=(),
    )

    code = main(
        [],
        load_settings=lambda: object(),
        migrate=lambda _settings, backup_root=None: result,
    )

    assert code == 0


def test_cli_returns_two_on_migrate_failure() -> None:
    def boom(_settings: object, backup_root: Path | None = None):
        raise MigrateSqliteError("nope")

    code = main(
        [],
        load_settings=lambda: object(),
        migrate=boom,
    )

    assert code == 2
