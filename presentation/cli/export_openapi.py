"""Export the FastAPI OpenAPI document for the Next.js typed client.

Run with::

    uv run python -m presentation.cli.export_openapi

Writes a byte-stable ``web/openapi/openapi.json`` (indent=2, sort_keys,
trailing newline). CORS is forced empty so the document does not depend on
HTTP CORS env. Importing ``presentation.http.app`` still loads Settings once
at module level; a malformed ``.env`` raises ``ConfigurationError``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from application.errors import ConfigurationError

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_OUTPUT = _REPO_ROOT / "web" / "openapi" / "openapi.json"


def export_openapi_document() -> dict[str, object]:
    """Build the OpenAPI document without CORS middleware side effects.

    Returns:
        dict[str, object]: OpenAPI schema from ``create_app().openapi()``.
    """
    from presentation.http.app import create_app

    return create_app(cors_origins=()).openapi()


def main(*, output_path: Path | None = None) -> int:
    """Serialize the OpenAPI document to *output_path*.

    Args:
        output_path: Destination JSON path. Defaults to ``web/openapi/openapi.json``.

    Returns:
        int: ``0`` on success, ``2`` when Settings fail during app import.
    """
    destination = output_path if output_path is not None else _DEFAULT_OUTPUT
    try:
        schema = export_openapi_document()
    except ConfigurationError as error:
        print(
            f"OpenAPI export failed: {error}. "
            "Fix Settings / .env, then retry.",
            file=sys.stderr,
        )
        return 2

    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    destination.write_text(payload, encoding="utf-8")
    print(f"wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
