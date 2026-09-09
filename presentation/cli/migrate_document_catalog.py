"""Import the JSON document catalog into the configured SQL workspace.

Run with::

    uv run python -m presentation.cli.migrate_document_catalog
"""

from __future__ import annotations

import sys

from application.errors import ConfigurationError
from composition import (
    DocumentOperationError,
    load_runtime_settings,
    migrate_document_catalog,
)


def main() -> int:
    """Migrate JSON catalog rows into SQLite.

    Returns:
        int: ``0`` on success, ``2`` for configuration failure, ``1`` for
        migration or import failure.
    """
    try:
        settings = load_runtime_settings()
        migrate_document_catalog(settings)
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    except DocumentOperationError as error:
        print(str(error), file=sys.stderr)
        return 1

    print("migrated_document_catalog=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
