"""Locked, atomic JSON files for Jira connector state (mode ``0600``)."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path


class ExclusiveLock:
    """Process-wide exclusive lock for one JSON grant/state path."""

    def __init__(self, path: Path) -> None:
        self._path = path.with_suffix(".lock.json")
        self._fd: int | None = None

    def __enter__(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self._path, os.O_CREAT | os.O_RDWR, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)

    def __exit__(self, *_exc: object) -> None:
        fd = self._fd
        if fd is None:
            return
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        self._fd = None


def read_json(path: Path) -> object:
    """Return the parsed JSON at ``path``, or ``None`` when absent or unreadable."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def atomic_write_json(path: Path, payload: object) -> None:
    """Write JSON to ``path`` at mode ``0600`` via temp file + ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="jira-tmp-", suffix=".json", dir=path.parent)
    handle = None
    try:
        os.fchmod(fd, 0o600)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = -1
        json.dump(payload, handle)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        handle = None
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    except BaseException:
        if handle is not None:
            handle.close()
        elif fd >= 0:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _fsync_dir(directory: Path) -> None:
    try:
        dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)
