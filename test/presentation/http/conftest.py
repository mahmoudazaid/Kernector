"""Shared fixtures for the HTTP presentation adapter tests."""

from __future__ import annotations

import pytest

from composition.auth import clear_auth_store_cache
from presentation.http.deps import (
    _clear_response_feedback_cached,
    _get_response_feedback_cached,
    _list_artifact_relationships_cached,
    _project_access_policy_cached,
    _project_use_cases_cached,
    _submit_response_feedback_cached,
    get_document_catalog,
    get_mcp_access_use_cases,
    get_prompt_repository,
    get_settings,
    get_short_term_memory_runtime,
    get_vector_store,
)


def _clear_caches() -> None:
    get_settings.cache_clear()
    get_vector_store.cache_clear()
    get_prompt_repository.cache_clear()
    get_document_catalog.cache_clear()
    get_short_term_memory_runtime.cache_clear()
    _submit_response_feedback_cached.cache_clear()
    _clear_response_feedback_cached.cache_clear()
    _get_response_feedback_cached.cache_clear()
    _project_use_cases_cached.cache_clear()
    _project_access_policy_cached.cache_clear()
    _list_artifact_relationships_cached.cache_clear()
    get_mcp_access_use_cases.cache_clear()
    clear_auth_store_cache()


@pytest.fixture(autouse=True)
def _clear_http_process_caches() -> None:
    """Process-wide ``lru_cache`` deps; clear around every test."""
    _clear_caches()
    yield
    _clear_caches()
