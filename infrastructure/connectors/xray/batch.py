"""Deployment-neutral create loop shared by the Xray importers.

Creates are sequential and never deduplicated. A rejection (Xray answered and
refused) is counted and the batch continues. Any other failure is ambiguous:
with nothing created it is raised; after at least one create the batch stops
and the remaining tests are reported failed, so nothing is blindly retried.
The only retry is one rediscovery when the very first create is rejected and
the metadata came from the cache.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

from domain.errors import ConnectorError
from domain.test_management.xray import XrayImportResult, XrayTestSpec
from infrastructure.connectors.xray.errors import XrayRejectedError

_M = TypeVar("_M")


def create_each(
    specs: Sequence[XrayTestSpec],
    *,
    mapping: _M,
    from_cache: bool,
    rediscover: Callable[[], _M],
    create: Callable[[XrayTestSpec, _M], str],
) -> XrayImportResult:
    created: list[str] = []
    failed = 0
    for index, spec in enumerate(specs):
        try:
            key = _attempt(create, spec, mapping)
            if key is None and from_cache and not created and failed == 0:
                from_cache = False
                mapping = rediscover()
                key = _attempt(create, spec, mapping)
        except ConnectorError:
            if not created:
                raise
            return XrayImportResult(
                created_keys=tuple(created), failed_count=failed + len(specs) - index
            )
        if key is None:
            failed += 1
        else:
            created.append(key)
    return XrayImportResult(created_keys=tuple(created), failed_count=failed)


def _attempt(
    create: Callable[[XrayTestSpec, _M], str], spec: XrayTestSpec, mapping: _M
) -> str | None:
    try:
        return create(spec, mapping)
    except XrayRejectedError:
        return None
