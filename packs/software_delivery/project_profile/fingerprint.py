"""Deterministic profile fingerprint over evidence and detectors (#387)."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

EvidenceTuple = tuple[str, str, str]
DetectorTuple = tuple[str, str]


def profile_fingerprint(
    evidence: Sequence[EvidenceTuple],
    detectors: Sequence[DetectorTuple],
) -> str:
    """Return a stable hex digest for identical evidence and detector sets.

    Canonical order:
    1. component labels lexicographically (implicit component uses ``""``)
    2. per component, evidence by ``(path, content_hash)``
    3. detectors by ``(detector_id, version)``
    """
    digest = hashlib.sha256()
    for component, path, content_hash in sorted(evidence, key=lambda item: item):
        digest.update(component.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(content_hash.encode("utf-8"))
        digest.update(b"\0")
    digest.update(b"|")
    for detector_id, version in sorted(detectors, key=lambda item: item):
        digest.update(detector_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(version.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()
