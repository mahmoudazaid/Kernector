"""Provider-neutral scenario controls every Test Design source harness exposes."""

from __future__ import annotations

from typing import Protocol

from composition.test_design.sources import TestDesignSource


class SourceContractHarness(Protocol):
    """Drive one provider's real ``TestDesignSource`` through contract scenarios.

    A harness starts connected and serving a non-empty item ``item-1``.
    ``upstream_calls`` counts provider requests for source items.
    """

    provider: str
    source_type: str
    raw_locators: tuple[str, ...]
    canonical_locator: str
    invalid_locators: tuple[str, ...]

    @property
    def upstream_calls(self) -> int: ...

    def source(self) -> TestDesignSource: ...

    def serve(self, body: str, *, item_id: str = "item-1") -> None: ...

    def disconnect(self) -> None: ...

    def reject_auth(self) -> None: ...

    def fail_not_found(self) -> None: ...
