"""Apply Kernector SQLite migrations before application traffic (#486).

Run with::

    uv run python -m presentation.cli.migrate_sqlite

Compose uses this as a oneshot service. Exit ``0`` on success; non-zero when
backup or migration fails so dependent services do not start.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from application.errors import ConfigurationError
from composition import load_runtime_settings
from composition.migrate_sqlite import (
    MigrateSqliteError,
    MigrateSqliteResult,
    run_sqlite_migrations,
)


def main(
    argv: Sequence[str] | None = None,
    *,
    load_settings: Callable[[], object] = load_runtime_settings,
    migrate: Callable[..., MigrateSqliteResult] = run_sqlite_migrations,
) -> int:
    """Back up existing SQLite files and apply migrations.

    Returns:
        int: ``0`` on success, ``2`` on configuration or migrate failure.
    """
    parser = argparse.ArgumentParser(
        prog="python -m presentation.cli.migrate_sqlite",
        description=(
            "Apply Kernector SQLite migrations idempotently "
            "with a pre-migrate backup of existing databases."
        ),
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Directory for pre-migrate SQLite copies (default: <catalog>/backups)",
    )
    try:
        args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as error:
        if error.code in (0, None):
            return 0
        return 2

    try:
        settings = load_settings()
        result = migrate(settings, backup_root=args.backup_dir)
    except (ConfigurationError, MigrateSqliteError) as error:
        print(f"migrate failed: {error}", file=sys.stderr)
        return 2

    print(
        "migrate ok: "
        f"catalog={result.catalog_path} "
        f"auth={result.auth_path} "
        f"workspace_store={result.workspace_store_path} "
        f"feedback={result.feedback_path} "
        f"backups={len(result.backups)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
