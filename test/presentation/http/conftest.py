"""Shared fixtures for the HTTP presentation adapter tests."""

from __future__ import annotations

import pytest

from presentation.http.deps import get_settings


@pytest.fixture(autouse=True)
def _clear_get_settings_cache() -> None:
    """``get_settings`` is process-wide ``lru_cache``; clear around every test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
