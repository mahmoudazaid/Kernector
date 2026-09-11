"""Filesystem adapter for durable upload payload blobs."""

from __future__ import annotations

import json
import os
import re
import struct
import threading
from pathlib import Path
from typing import ClassVar

from domain.knowledge import SourceReference, UploadPayload

__all__ = [
    "FilesystemUploadBlobStore",
    "UploadBlobError",
    "UploadBlobValidationError",
]

_SOURCE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
_MAGIC = b"KUPLOAD1"
_HEADER_LENGTH = struct.Struct(">I")


class UploadBlobError(RuntimeError):
    """Base error raised by upload blob storage adapters."""


class UploadBlobValidationError(UploadBlobError):
    """The upload blob reference cannot be mapped to a safe file path."""


class FilesystemUploadBlobStore:
    """Persist upload payloads as atomic flat files under one root."""

    _locks: ClassVar[dict[str, threading.Lock]] = {}
    _locks_guard: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self, root: Path) -> None:
        """Create an adapter bound to ``root``.

        Args:
            root (Path): Directory where blobs are stored as ``<root>/<source_id>``.
        """
        self._root = root

    def put(self, reference: SourceReference, payload: UploadPayload) -> None:
        """Store ``payload`` under ``reference``, replacing any existing blob."""
        final = self._path_for(reference)
        lock = self._lock_for(final)
        temporary = final.with_name(
            f".{final.name}.tmp.{os.getpid()}.{threading.get_ident()}"
        )
        with lock:
            try:
                if not self._root.exists():
                    self._root.mkdir(parents=True, exist_ok=True)
                with temporary.open("wb") as handle:
                    handle.write(_pack_payload(payload))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, final)
            except OSError as error:
                temporary.unlink(missing_ok=True)
                raise UploadBlobError(
                    f"could not write upload blob at {final}"
                ) from error

    def get(self, reference: SourceReference) -> UploadPayload | None:
        """Return the stored payload for ``reference``, or ``None`` when absent."""
        path = self._path_for(reference)
        with self._lock_for(path):
            try:
                blob = path.read_bytes()
            except FileNotFoundError:
                return None
            except OSError as error:
                raise UploadBlobError(
                    f"could not read upload blob at {path}"
                ) from error
        return _unpack_payload(blob, path=path)

    def delete(self, reference: SourceReference) -> None:
        """Remove the stored payload for ``reference``. Missing blobs are a no-op."""
        path = self._path_for(reference)
        with self._lock_for(path):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                raise UploadBlobError(
                    f"could not delete upload blob at {path}"
                ) from error

    def _lock_for(self, path: Path) -> threading.Lock:
        key = str(path)
        with self._locks_guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def _path_for(self, reference: SourceReference) -> Path:
        source_id = reference.source_id
        if _SOURCE_ID_PATTERN.fullmatch(source_id) is None:
            raise UploadBlobValidationError(
                "source_id must be 1-64 URL-safe identifier characters"
            )

        root = self._root.resolve(strict=False)
        path = self._root / source_id
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise UploadBlobValidationError("source_id resolves outside upload root")
        return resolved


def _pack_payload(payload: UploadPayload) -> bytes:
    header = json.dumps(
        {"file_name": payload.file_name},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return b"".join(
        (
            _MAGIC,
            _HEADER_LENGTH.pack(len(header)),
            header,
            bytes(payload.content),
        )
    )


def _unpack_payload(blob: bytes, *, path: Path) -> UploadPayload:
    prefix_size = len(_MAGIC) + _HEADER_LENGTH.size
    if len(blob) < prefix_size or blob[: len(_MAGIC)] != _MAGIC:
        raise UploadBlobError(f"upload blob at {path} is not valid")
    header_size = _HEADER_LENGTH.unpack(blob[len(_MAGIC) : prefix_size])[0]
    header_end = prefix_size + header_size
    if len(blob) < header_end:
        raise UploadBlobError(f"upload blob at {path} is not valid")
    try:
        header = json.loads(blob[prefix_size:header_end].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UploadBlobError(f"upload blob at {path} is not valid") from error
    if not isinstance(header, dict):
        raise UploadBlobError(f"upload blob at {path} is not valid")
    file_name = header.get("file_name")
    if not isinstance(file_name, str) or not file_name.strip():
        raise UploadBlobError(f"upload blob at {path} is not valid")
    return UploadPayload(file_name=file_name, content=blob[header_end:])
