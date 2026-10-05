"""Source-neutral seam for the live evidence behind Test Design drafts.

Providers plug in by implementing :class:`TestDesignSource` and being
registered by the composition root. Nothing here knows about a concrete
provider.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from composition.test_design.errors import (
    TestDesignUnavailableError,
    TestDesignValidationError,
    UnsupportedSourceLocatorError,
)
from domain.knowledge import SourceLocator, SourceType
from domain.ports import LiveSourceReader


class AmbiguousSourceLocatorError(ValueError):
    """Free text references more than one distinct source item."""


class TestDesignSource(Protocol):
    """One live provider Test Design can plan coverage from.

    ``canonicalize`` raises ``TestDesignValidationError`` for malformed
    locators. ``extract_locator`` raises ``AmbiguousSourceLocatorError`` when
    the text references several distinct items. ``reader`` raises
    ``SourceNotConnectedError`` when credentials are missing or
    ``SourceReauthorizationRequiredError`` when the stored grant was rejected.
    The returned reader raises only ``InsufficientEvidenceError``,
    ``SourceItemNotFoundError``, ``SourceReauthorizationRequiredError`` or
    ``TestDesignValidationError`` for provider-specific evidence problems.
    """

    __test__ = False

    @property
    def provider(self) -> str: ...

    def canonicalize(self, locator: str) -> str: ...

    def extract_locator(self, text: str) -> str | None: ...

    def reader(self) -> LiveSourceReader: ...


class TestDesignSourceRegistry:
    """Resolve Test Design sources by provider name (case-insensitive)."""

    __test__ = False

    def __init__(self, sources: Iterable[TestDesignSource]) -> None:
        by_provider: dict[str, TestDesignSource] = {}
        for source in sources:
            key = _provider_key(source.provider)
            if key is None:
                raise ValueError("source provider must be non-empty")
            if key in by_provider:
                raise ValueError(f"duplicate Test Design source: {key}")
            by_provider[key] = source
        self._by_provider = by_provider
        self._known = frozenset(item.value for item in SourceType) | frozenset(
            by_provider
        )

    def resolve(self, provider: str) -> TestDesignSource:
        """Return the registered source for *provider*.

        Raises:
            TestDesignValidationError: Provider is blank or not a known source.
            TestDesignUnavailableError: Provider is known but not registered.
        """
        key = _provider_key(provider)
        if key is None:
            raise TestDesignValidationError("source_locator.provider must be non-empty")
        source = self._by_provider.get(key)
        if source is not None:
            return source
        if key in self._known:
            raise TestDesignUnavailableError("test design source unavailable")
        raise TestDesignValidationError("source_locator.provider is not supported")

    def resolve_locator(self, locator: str) -> SourceLocator:
        """Return the one registered source that accepts *locator*, canonicalized.

        A source's ``TestDesignValidationError`` means "not my locator" and is
        skipped; any other error propagates, so ``canonicalize`` must stay pure.

        Raises:
            UnsupportedSourceLocatorError: No source accepts *locator*.
            TestDesignValidationError: Several sources accept *locator*.
        """
        found: list[SourceLocator] = []
        for source in self._by_provider.values():
            try:
                canonical = source.canonicalize(locator)
            except TestDesignValidationError:
                continue
            found.append(SourceLocator(provider=source.provider, locator=canonical))
        if not found:
            raise UnsupportedSourceLocatorError(
                "locator is not a supported source locator"
            )
        if len(found) > 1:
            raise TestDesignValidationError("locator is ambiguous across sources")
        return found[0]

    def extract_locator(self, text: str) -> SourceLocator | None:
        """Return the one source item referenced in *text*, if any.

        Raises:
            AmbiguousSourceLocatorError: Several distinct items are referenced.
        """
        found: list[SourceLocator] = []
        for source in self._by_provider.values():
            locator = source.extract_locator(text)
            if locator is not None:
                found.append(SourceLocator(provider=source.provider, locator=locator))
        if len(found) > 1:
            raise AmbiguousSourceLocatorError("Query must reference exactly one source")
        return found[0] if found else None


def _provider_key(provider: object) -> str | None:
    if not isinstance(provider, str) or not provider.strip():
        return None
    return provider.strip().casefold()
