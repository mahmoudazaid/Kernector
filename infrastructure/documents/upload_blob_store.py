"""Filesystem adapter for durable upload payload blobs."""

from __future__ import annotations

from collections import OrderedDict
from contextlib import contextmanager
import json
import os
import re
import struct
import threading
from collections.abc import Iterator
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
_MAX_PATH_LOCKS = 256


class UploadBlobError(RuntimeError):
    """Base error raised by upload blob storage adapters."""


class UploadBlobValidationError(UploadBlobError):
    """The upload blob reference cannot be mapped to a safe file path."""


class FilesystemUploadBlobStore:
    """Persist upload payloads as atomic flat files under one root."""

    _locks: ClassVar[OrderedDict[str, tuple[threading.Lock, int]]] = OrderedDict()
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
        temporary = final.with_name(
            f".{final.name}.tmp.{os.getpid()}.{threading.get_ident()}"
        )
        with self._path_lock(final):
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
        with self._path_lock(path):
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
        """Remove the stored payload for ``reference``. Missing blobs are a no-op.

        References that cannot be mapped to a safe path are also a no-op so
        catalog deletes stay idempotent for unknown or Drive-shaped ids.
        """
        try:
            path = self._path_for(reference)
        except UploadBlobValidationError:
            return
        with self._path_lock(path):
            try:
                path.unlink(missing_ok=True)
            except OSError as error:
                raise UploadBlobError(
                    f"could not delete upload blob at {path}"
                ) from error

    @contextmanager
    def _path_lock(self, path: Path) -> Iterator[None]:
        lock = self._acquire_lock(path)
        lock.acquire()
        try:
            yield
        finally:
            lock.release()
            self._release_lock(path)

    def _acquire_lock(self, path: Path) -> threading.Lock:
        key = str(path)
        with self._locks_guard:
            entry = self._locks.get(key)
            if entry is None:
                while len(self._locks) >= _MAX_PATH_LOCKS:
                    evicted = False
                    for candidate_key, (_candidate, refs) in list(
                        self._locks.items()
                    ):
                        if refs == 0:
                            del self._locks[candidate_key]
                            evicted = True
                            break
                    if not evicted:
                        break
                lock = threading.Lock()
                self._locks[key] = (lock, 1)
                return lock
            lock, refs = entry
            self._locks[key] = (lock, refs + 1)
            self._locks.move_to_end(key)
            return lock

    def _release_lock(self, path: Path) -> None:
        key = str(path)
        with self._locks_guard:
            entry = self._locks.get(key)
            if entry is None:
                return
            lock, refs = entry
            refs = max(0, refs - 1)
            self._locks[key] = (lock, refs)
            self._locks.move_to_end(key)

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
