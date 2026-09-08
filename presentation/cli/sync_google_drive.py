"""Synchronize Google Drive documents into the knowledge base.

Run with::

    uv run python -m presentation.cli.sync_google_drive
"""

from __future__ import annotations

import sys

from application.contracts import ConnectorSyncStatus
from application.errors import ConfigurationError
from composition import ConnectorSyncError, load_runtime_settings, sync_google_drive

_SYNC_FAILED = "The Google Drive connector sync failed."


def main() -> int:
    """Run a Drive folder sync and print scheduler-safe counts.

    Returns:
        int: ``0`` when every listed document was ingested or skipped, ``1``
        when at least one document failed or the run aborted, ``2`` when
        connector or embedding configuration is invalid.
    """
    try:
        settings = load_runtime_settings()
        response = sync_google_drive(settings)
    except ConfigurationError as error:
        print(str(error), file=sys.stderr)
        return 2
    except ConnectorSyncError as error:
        print(str(error), file=sys.stderr)
        return 1
    except RuntimeError:
        print(_SYNC_FAILED, file=sys.stderr)
        return 1

    print(f"ingested={response.ingested_count}")
    print(f"skipped={response.skipped_count}")
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
