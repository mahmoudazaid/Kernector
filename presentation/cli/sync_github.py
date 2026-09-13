"""Synchronize GitHub documents into the knowledge base.

Run with::

    uv run python -m presentation.cli.sync_github
"""

from __future__ import annotations

import sys

from application.contracts import ConnectorSyncStatus
from application.errors import ConfigurationError
from composition import ConnectorSyncError, load_runtime_settings, sync_github


def main() -> int:
    """Run a GitHub sync and print scheduler-safe counts."""
    try:
        settings = load_runtime_settings()
        response = sync_github(settings)
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    except ConnectorSyncError as error:
        print(str(error), file=sys.stderr)
        return 1

    discovered = (
        response.ingested_count
        + response.updated_count
        + response.skipped_count
        + response.failed_count
    )
    print(f"discovered={discovered}")
    print(f"ingested={response.ingested_count}")
    print(f"updated={response.updated_count}")
    print(f"skipped={response.skipped_count}")
    print(f"removed={response.removed_count}")
    print(f"failed={response.failed_count}")
    for outcome in response.outcomes:
        if outcome.status is ConnectorSyncStatus.FAILED:
            print(
                f"failed source_id={outcome.source_id} error_type={outcome.error_type}",
                file=sys.stderr,
            )
    return 1 if response.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
