"""Streamlit shares one cached vector store across chat and document mutations."""

from pathlib import Path


def _app_source() -> str:
    import presentation.streamlit.app as app_mod

    return Path(app_mod.__file__).read_text(encoding="utf-8")


def test_streamlit_caches_vector_store_and_injects_into_chat_and_uploads() -> None:
    source = _app_source()

    assert "@st.cache_resource" in source
    assert "def _vector_store()" in source
    assert "build_vector_store(_settings())" in source
    assert "vector_store=vector_store" in source
    assert "build_tool_augmented_ask(" in source
    assert "_render_upload_ingest(settings, vector_store=vector_store)" in source
