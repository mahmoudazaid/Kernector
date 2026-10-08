"""Per-deployment, per-project cache of discovered Xray create metadata.

Only metadata is cached (test types, field ids, option values); never test
content. Entries live until explicitly invalidated, which the importers do
once when a create is rejected in a way that suggests the metadata drifted.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TypeVar

SchemaKey = tuple[str, str, str]
"""``(deployment, base_url, project_key)``."""

_T = TypeVar("_T")


class XraySchemaCache:
    """Thread-safe store of discovered metadata keyed by :data:`SchemaKey`."""

    def __init__(self) -> None:
        self._entries: dict[SchemaKey, object] = {}
        self._lock = threading.Lock()

    def get_or_discover(self, key: SchemaKey, discover: Callable[[], _T]) -> tuple[_T, bool]:
        """Return ``(metadata, from_cache)``, discovering and storing on a miss."""
        with self._lock:
            if key in self._entries:
                return self._entries[key], True  # type: ignore[return-value]
        value = discover()
        with self._lock:
            self._entries[key] = value
        return value, False

    def invalidate(self, key: SchemaKey) -> None:
        with self._lock:
            self._entries.pop(key, None)
