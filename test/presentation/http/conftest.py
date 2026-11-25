"""Shared fixtures for the HTTP presentation adapter tests."""

from __future__ import annotations

import pytest

from composition.auth import clear_auth_store_cache
from presentation.http.deps import (
    get_document_catalog,
    get_prompt_repository,
    get_settings,
    get_short_term_memory_runtime,
    get_vector_store,
    get_clear_response_feedback,
    get_get_response_feedback,
    get_mcp_access_use_cases,
    get_project_use_cases,
    get_submit_response_feedback,
)


@pytest.fixture(autouse=True)
def _clear_http_process_caches() -> None:
    """Process-wide ``lru_cache`` deps; clear around every test."""
    get_settings.cache_clear()
    get_vector_store.cache_clear()
    get_prompt_repository.cache_clear()
    get_document_catalog.cache_clear()
    get_short_term_memory_runtime.cache_clear()
    get_submit_response_feedback.cache_clear()
    get_clear_response_feedback.cache_clear()
    get_get_response_feedback.cache_clear()
    get_project_use_cases.cache_clear()
    get_mcp_access_use_cases.cache_clear()
    clear_auth_store_cache()
    yield
    get_settings.cache_clear()
    get_vector_store.cache_clear()
    get_prompt_repository.cache_clear()
    get_document_catalog.cache_clear()
    get_short_term_memory_runtime.cache_clear()
    get_submit_response_feedback.cache_clear()
    get_clear_response_feedback.cache_clear()
    get_get_response_feedback.cache_clear()
    get_project_use_cases.cache_clear()
    get_mcp_access_use_cases.cache_clear()
    clear_auth_store_cache()
