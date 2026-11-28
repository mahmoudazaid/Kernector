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
        migrate=lambda _settings, backup_root=None, keep=5: result,
    )

    assert code == 0


def test_cli_returns_two_on_migrate_failure(
    tmp_path: Path, capsys
) -> None:
    backup = tmp_path / "catalog-20260101T000000Z.sqlite"
    backup.write_bytes(b"x")

    def boom(_settings: object, backup_root: Path | None = None, keep: int = 5):
        raise MigrateSqliteError("nope", backups=(backup,))

    code = main(
        [],
        load_settings=lambda: object(),
        migrate=boom,
    )

    assert code == 2
    assert "backups=1" in capsys.readouterr().err


def test_cli_rejects_negative_keep() -> None:
    code = main(
        ["--keep", "-1"],
        load_settings=lambda: object(),
        migrate=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("migrate should not run")
        ),
    )

    assert code == 2
