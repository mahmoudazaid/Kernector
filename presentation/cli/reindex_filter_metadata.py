"""Promote stored ``extra`` metadata so filters work on legacy Chroma records.

Run with::

    uv run python -m presentation.cli.reindex_filter_metadata

Records written before filterable ``x:`` promotion carry only ``extra_json``.
This command rewrites metadata in place without re-embedding. Prefer a full
corpus re-ingest when source documents and chunk settings must also change.
"""

from __future__ import annotations

import sys

from composition import load_runtime_settings, reindex_filter_metadata


def main() -> int:
    """Rewrite filter metadata for every stored chunk.

    Returns:
        int: ``0`` on success, ``1`` for store failure.
    """
    try:
        settings = load_runtime_settings()
        rewritten = reindex_filter_metadata(settings)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1

    print(f"rewritten_records={rewritten}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
