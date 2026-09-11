"""Behavior tests for the filesystem upload blob store."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from domain.knowledge import SourceReference, SourceType, UploadPayload
from infrastructure.documents.upload_blob_store import (
    FilesystemUploadBlobStore,
    UploadBlobError,
    UploadBlobValidationError,
)


def _reference(source_id: str = "upload_1") -> SourceReference:
    return SourceReference(source_id, SourceType.KNOWLEDGE_DOCUMENT)


def _payload(content: bytes = b"hello") -> UploadPayload:
    return UploadPayload(file_name="guide.md", content=content)


def test_put_get_delete_round_trip(tmp_path: Path) -> None:
    store = FilesystemUploadBlobStore(tmp_path / "uploads")
    reference = _reference()
    payload = _payload(b"# Guide\n")

    store.put(reference, payload)

    assert store.get(reference) == payload
    store.delete(reference)
    assert store.get(reference) is None


def test_missing_key_returns_none(tmp_path: Path) -> None:
    store = FilesystemUploadBlobStore(tmp_path / "uploads")

    assert store.get(_reference("missing")) is None


def test_replace_overwrites_previous_blob(tmp_path: Path) -> None:
    store = FilesystemUploadBlobStore(tmp_path / "uploads")
    reference = _reference()

    store.put(reference, _payload(b"old bytes"))
    replacement = UploadPayload(file_name="guide-v2.md", content=b"new bytes")
    store.put(reference, replacement)

    assert store.get(reference) == replacement


@pytest.mark.parametrize("bad_source_id", ["..", ".", "a b", "a" * 65])
def test_put_rejects_invalid_source_id_before_filesystem_access(
    tmp_path: Path, bad_source_id: str
) -> None:
    root = tmp_path / "missing-root"
    store = FilesystemUploadBlobStore(root)

    with pytest.raises(UploadBlobValidationError):
        store.put(_reference(bad_source_id), _payload())

    assert not root.exists()


@pytest.mark.parametrize("bad_source_id", ["..", ".", "a b", "a" * 65])
def test_get_rejects_invalid_source_id_before_filesystem_access(
    tmp_path: Path, bad_source_id: str
) -> None:
    root = tmp_path / "missing-root"
    store = FilesystemUploadBlobStore(root)

    with pytest.raises(UploadBlobValidationError):
        store.get(_reference(bad_source_id))

    assert not root.exists()


@pytest.mark.parametrize("bad_source_id", ["..", ".", "a b", "a" * 65])
def test_delete_invalid_source_id_is_noop_before_filesystem_access(
    tmp_path: Path, bad_source_id: str
) -> None:
    root = tmp_path / "missing-root"
    store = FilesystemUploadBlobStore(root)

    store.delete(_reference(bad_source_id))

    assert not root.exists()


def test_crafted_id_cannot_resolve_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "uploads"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.write_bytes(b"secret")
    (root / "safe_id").symlink_to(outside)
    store = FilesystemUploadBlobStore(root)

    with pytest.raises(UploadBlobValidationError):
        store.get(_reference("safe_id"))

    with pytest.raises(UploadBlobValidationError):
        store.delete(_reference("safe_id"))


def test_adapter_errors_share_one_public_base() -> None:
    assert issubclass(UploadBlobValidationError, UploadBlobError)


def test_failed_replace_leaves_previous_blob_and_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import infrastructure.documents.upload_blob_store as upload_blob_store

    root = tmp_path / "uploads"
    store = FilesystemUploadBlobStore(root)
    reference = _reference()
    original = _payload(b"original")
    store.put(reference, original)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(upload_blob_store.os, "replace", boom)

    with pytest.raises(UploadBlobError):
        store.put(reference, _payload(b"replacement"))

    assert store.get(reference) == original
    assert sorted(path.name for path in root.iterdir()) == [reference.source_id]


def test_get_during_put_returns_only_complete_old_or_new_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import infrastructure.documents.upload_blob_store as upload_blob_store

    root = tmp_path / "uploads"
    store = FilesystemUploadBlobStore(root)
    reference = _reference()
    old_payload = _payload(b"a" * 20_000)
    new_payload = _payload(b"b" * 20_000)
    store.put(reference, old_payload)

    replace_entered = threading.Event()
    allow_replace = threading.Event()
    real_replace = upload_blob_store.os.replace

    def gated_replace(src: object, dst: object) -> None:
        replace_entered.set()
        allow_replace.wait(timeout=5)
        real_replace(src, dst)

    monkeypatch.setattr(upload_blob_store.os, "replace", gated_replace)
    errors: list[BaseException] = []
    observed: list[bytes] = []

    def writer() -> None:
        try:
            store.put(reference, new_payload)
        except BaseException as error:  # noqa: BLE001 - asserted below.
            errors.append(error)

    def reader() -> None:
        try:
            replace_entered.wait(timeout=5)
            observed_payload = store.get(reference)
            assert observed_payload is not None
            observed.append(observed_payload.content)
        except BaseException as error:  # noqa: BLE001 - asserted below.
            errors.append(error)

    writer_thread = threading.Thread(target=writer)
    reader_thread = threading.Thread(target=reader)
    writer_thread.start()
    reader_thread.start()

    assert replace_entered.wait(timeout=5)
    allow_replace.set()
    writer_thread.join(timeout=5)
    reader_thread.join(timeout=5)

    assert errors == []
    assert observed == [new_payload.content]
    assert store.get(reference) == new_payload


def test_lock_registry_does_not_evict_a_held_lock(tmp_path: Path) -> None:
    from infrastructure.documents import upload_blob_store as module

    store = FilesystemUploadBlobStore(tmp_path / "uploads")
    path = store._path_for(_reference("held"))
    lock_a = store._acquire_lock(path)
    lock_a.acquire()
    try:
        for index in range(module._MAX_PATH_LOCKS + 5):
            other = store._path_for(_reference(f"doc-{index}"))
            store._acquire_lock(other)
            store._release_lock(other)
        lock_b = store._acquire_lock(path)
        assert lock_b is lock_a
        assert lock_b.locked()
        assert not lock_b.acquire(blocking=False)
        store._release_lock(path)
    finally:
        lock_a.release()
        store._release_lock(path)
