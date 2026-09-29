"""Persisted Jira Data Center connector state. The Personal Access Token is never stored."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from infrastructure.connectors.jira.json_file import (
    ExclusiveLock,
    atomic_write_json,
    read_json,
)
from infrastructure.connectors.jira.site import JiraSite


@dataclass(frozen=True, slots=True)
class JiraDataCenterState:
    """Instance identity, selected projects, and last-sync summary for one workspace."""

    connector_id: str | None = None
    site: JiraSite | None = None
    project_keys: tuple[str, ...] = ()
    last_synced_at: str | None = None
    last_sync_new: int | None = None
    last_sync_updated: int | None = None
    last_sync_unchanged: int | None = None
    last_sync_removed: int | None = None
    last_sync_failed: int | None = None
    credentials_rejected: bool = False


class StateStoreDelete:
    """Mutator result that unlinks the state file."""


DELETE_STATE = StateStoreDelete()


class JiraDataCenterStateStore:
    """Locked JSON file (mode ``0600``) holding :class:`JiraDataCenterState`."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> JiraDataCenterState | None:
        """Return the stored state, or ``None`` when nothing is saved."""
        return _state_from_payload(read_json(self._path))

    def clear(self) -> None:
        """Delete the stored state under the store lock."""
        self.mutate(lambda _current: DELETE_STATE)

    def mutate(
        self,
        mutator: Callable[
            [JiraDataCenterState | None],
            JiraDataCenterState | StateStoreDelete | None,
        ],
    ) -> JiraDataCenterState | None:
        """Re-read, apply ``mutator``, and persist atomically; ``None`` keeps the state."""
        with ExclusiveLock(self._path):
            current = _state_from_payload(read_json(self._path))
            next_value = mutator(current)
            if next_value is None:
                return current
            if isinstance(next_value, StateStoreDelete):
                try:
                    self._path.unlink()
                except FileNotFoundError:
                    pass
                return None
            atomic_write_json(self._path, _state_payload(next_value))
            return next_value


def _state_from_payload(raw: object) -> JiraDataCenterState | None:
    if not isinstance(raw, dict):
        return None
    keys = raw.get("project_keys")
    return JiraDataCenterState(
        connector_id=_optional_str(raw.get("connector_id")),
        site=_site_from_payload(raw.get("site")),
        project_keys=tuple(k for k in keys if isinstance(k, str) and k)
        if isinstance(keys, list)
        else (),
        last_synced_at=_optional_str(raw.get("last_synced_at")),
        last_sync_new=_optional_int(raw.get("last_sync_new")),
        last_sync_updated=_optional_int(raw.get("last_sync_updated")),
        last_sync_unchanged=_optional_int(raw.get("last_sync_unchanged")),
        last_sync_removed=_optional_int(raw.get("last_sync_removed")),
        last_sync_failed=_optional_int(raw.get("last_sync_failed")),
        credentials_rejected=raw.get("credentials_rejected") is True,
    )


def _site_from_payload(raw: object) -> JiraSite | None:
    if not isinstance(raw, dict):
        return None
    instance_id = _optional_str(raw.get("instance_id"))
    site_url = _optional_str(raw.get("site_url"))
    if instance_id is None or site_url is None:
        return None
    return JiraSite(
        cloud_id=instance_id,
        site_url=site_url,
        name=_optional_str(raw.get("name")) or site_url,
    )


def _state_payload(state: JiraDataCenterState) -> dict[str, object]:
    site = state.site
    return {
        "connector_id": state.connector_id,
        "site": None
        if site is None
        else {"instance_id": site.instance_id, "site_url": site.site_url, "name": site.name},
        "project_keys": list(state.project_keys),
        "last_synced_at": state.last_synced_at,
        "last_sync_new": state.last_sync_new,
        "last_sync_updated": state.last_sync_updated,
        "last_sync_unchanged": state.last_sync_unchanged,
        "last_sync_removed": state.last_sync_removed,
        "last_sync_failed": state.last_sync_failed,
        "credentials_rejected": state.credentials_rejected,
    }


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
