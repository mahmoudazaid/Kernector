"""Streamlit app: page flow."""

from collections.abc import Mapping
from dataclasses import dataclass

import streamlit as st

from application.ask_service import AskService
from composition import (
    SUPPORTED_UPLOAD_SUFFIXES,
    Settings,
    available_providers,
    build_ask_service,
    build_chat_model,
    build_prompt_repository,
    load_runtime_settings,
    probe_ollama,
)
from domain.models import Message, PromptVariant
from domain.ports import PromptRepository
from domain.validation import validate_input
from presentation.streamlit.components import (
    render_export_actions,
    render_model_settings,
    render_reply,
    render_run_meta,
)
from presentation.streamlit.upload_ingest import (
    create_new_document,
    delete_existing_document,
    load_uploaded_documents,
    replace_existing_document,
)

_PROVIDER_LABELS = {"openrouter": "OpenRouter", "ollama": "Ollama"}


@dataclass(frozen=True, slots=True)
class _SidebarState:
    provider: str
    model: str
    ollama_base_url: str
    settings: Mapping[str, object]
    prompt_key: str


@st.cache_resource
def _settings() -> Settings:
    return load_runtime_settings()


@st.cache_resource
def _prompt_repository() -> PromptRepository:
    return build_prompt_repository()


@st.cache_data(ttl=30)
def _cached_probe(_settings: Settings, base_url: str) -> dict:
    return probe_ollama(_settings, base_url)


def _render_sidebar(settings: Settings, repository: PromptRepository) -> _SidebarState:
    prompts = repository.all()

    providers = available_providers()
    provider = st.radio(
        "Provider",
        providers,
        format_func=lambda p: _PROVIDER_LABELS.get(p, p.title()),
        index=providers.index(settings.provider) if settings.provider in providers else 0,
    )

    if st.button("New chat", icon=":material/add_comment:", width="stretch"):
        st.session_state.messages = []

    selected_model = settings.openrouter.model
    ollama_base_url = settings.ollama.base_url

    if provider == "ollama":
        ollama_base_url = st.text_input("Ollama base URL", value=ollama_base_url)
        status = _cached_probe(settings, ollama_base_url)
        models = status["models"]

        if not status["reachable"]:
            st.error("Ollama is not reachable.")
            st.markdown(
                "1. Install Ollama from [ollama.com/download](https://ollama.com/download)\n"
                "2. Open the Ollama app (starts the local server)\n"
                "3. In a terminal, run: `ollama pull llama3.2`\n"
                "4. Refresh this page"
            )
            st.caption(
                "`ollama pull` only works after Ollama is installed. "
                "If you see `command not found`, finish step 1 first."
            )
            selected_model = st.text_input(
                "Ollama model", value=settings.ollama.model
            )
        elif not models:
            st.warning("Ollama is running, but no models are installed yet.")
            st.markdown("In a terminal, run: `ollama pull llama3.2`, then refresh.")
            selected_model = st.text_input(
                "Ollama model", value=settings.ollama.model
            )
        else:
            default_model = settings.ollama.model or models[0]
            index = models.index(default_model) if default_model in models else 0
            selected_model = st.selectbox("Ollama model", options=models, index=index)
            st.caption("Ollama connected · local, slower, no API cost.")
    else:
        openrouter_models = settings.openrouter.models
        if openrouter_models:
            default_model = settings.openrouter.model or openrouter_models[0]
            index = (
                openrouter_models.index(default_model)
                if default_model in openrouter_models
                else 0
            )
            selected_model = st.selectbox(
                "OpenRouter model", options=openrouter_models, index=index
            )
        else:
            selected_model = st.text_input(
                "OpenRouter model", value=settings.openrouter.model
            )
            st.caption("No OpenRouter models available")

    settings_values = render_model_settings(provider)

    keys = list(prompts.keys())
    prompt_key = st.selectbox(
        "Prompt variant",
        options=keys,
        format_func=lambda key: prompts[key].name,
        index=keys.index(repository.default_key()),
    )
    st.caption(prompts[prompt_key].description)

    return _SidebarState(
        provider=provider,
        model=selected_model,
        ollama_base_url=ollama_base_url,
        settings=settings_values,
        prompt_key=prompt_key,
    )


def _render_history() -> None:
    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_run_meta(message["result"])
                render_reply(message["content"], message.get("off_topic_marker"))
                render_export_actions(message["content"], f"analysis_{index}")
            else:
                st.markdown(message["content"])


def _handle_input(
    service: AskService,
    prompt: PromptVariant,
    settings: Mapping[str, object],
    max_input_length: int,
) -> None:
    user_input = st.chat_input("Start typing...")
    if not user_input:
        return

    error = validate_input(user_input, max_input_length)
    if error:
        st.error(error)
        return

    history = [
        Message(role=m["role"], content=m["content"])
        for m in st.session_state.messages
    ]
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = service.ask(
                prompt.system,
                user_input,
                settings=settings,
                history=history,
            )
        render_run_meta(result)
        render_reply(result.content, prompt.off_topic_marker)
        render_export_actions(
            result.content, f"analysis_{len(st.session_state.messages)}"
        )

    st.session_state.messages.append({
        "role": "assistant",
        "content": result.content,
        "result": result,
        "off_topic_marker": prompt.off_topic_marker,
    })


def _render_upload_ingest(settings: Settings) -> None:
    """List uploaded documents and support create, explicit replace, and delete.

    The in-progress flag is a submit-guard for ordinary repeated clicks, not a
    concurrency primitive: a Streamlit rerun can interrupt the prior script run.
    """
    st.subheader("Uploaded documents")
    try:
        documents = list(load_uploaded_documents(settings))
    except Exception as error:  # noqa: BLE001 — show list failures without traceback
        st.error(f"Could not load uploaded documents: {error}")
        documents = []

    if documents:
        labels = {
            f"{doc.file_name} · {doc.status.value} · {doc.reference.source_id}": doc
            for doc in documents
        }
        selected_label = st.selectbox(
            "Managed documents",
            options=list(labels.keys()),
            help="Select a document to replace or delete. Matching filenames never "
            "replace automatically — choose Replace explicitly.",
        )
        selected = labels[selected_label]
        st.caption(
            f"Status: {selected.status.value} · chunks: {selected.chunk_count} · "
            f"uploaded: {selected.uploaded_at.isoformat()}"
        )
        if selected.error:
            st.warning(selected.error)
    else:
        selected = None
        st.caption(
            "No uploaded documents yet. Seed-corpus documents are managed separately "
            "and do not appear here."
        )

    st.subheader("Upload new document")
    st.caption("A system-managed source ID is assigned automatically.")
    with st.form("document_upload_new"):
        uploaded = st.file_uploader(
            "Document",
            type=sorted(suffix.lstrip(".") for suffix in SUPPORTED_UPLOAD_SUFFIXES),
            accept_multiple_files=False,
            key="upload_new_file",
        )
        submitted_new = st.form_submit_button(
            "Upload new",
            disabled=bool(st.session_state.get("ingest_in_progress")),
        )
    if submitted_new:
        result = create_new_document(
            settings,
            filename=uploaded.name if uploaded is not None else None,
            content=uploaded.getvalue() if uploaded is not None else None,
            session=st.session_state,
        )
        if result.ok:
            st.success(result.message)
            if result.should_rerun:
                st.rerun()
        else:
            st.error(result.message)

    if selected is None:
        return

    st.subheader("Replace selected document")
    st.caption("Keeps the same source ID and replaces stored chunks.")
    with st.form("document_upload_replace"):
        replacement = st.file_uploader(
            "Replacement document",
            type=sorted(suffix.lstrip(".") for suffix in SUPPORTED_UPLOAD_SUFFIXES),
            accept_multiple_files=False,
            key="upload_replace_file",
        )
        submitted_replace = st.form_submit_button(
            "Replace",
            disabled=bool(st.session_state.get("ingest_in_progress")),
        )
    if submitted_replace:
        result = replace_existing_document(
            settings,
            reference=selected.reference,
            filename=replacement.name if replacement is not None else None,
            content=replacement.getvalue() if replacement is not None else None,
            session=st.session_state,
        )
        if result.ok:
            st.success(result.message)
            if result.should_rerun:
                st.rerun()
        else:
            st.error(result.message)

    st.subheader("Delete selected document")
    confirm = st.checkbox(
        f"Confirm delete of {selected.file_name}",
        key=f"confirm_delete_{selected.reference.source_id}",
    )
    if st.button(
        "Delete",
        disabled=not confirm or bool(st.session_state.get("ingest_in_progress")),
    ):
        result = delete_existing_document(
            settings,
            reference=selected.reference,
            session=st.session_state,
        )
        if result.ok:
            st.success(result.message)
            if result.should_rerun:
                st.rerun()
        else:
            st.error(result.message)


def render() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("ingest_in_progress", False)

    settings = _settings()
    repository = _prompt_repository()

    st.title("Kernector")

    with st.sidebar:
        state = _render_sidebar(settings, repository)

    _render_upload_ingest(settings)

    service = build_ask_service(
        build_chat_model(
            settings,
            provider=state.provider,
            model=state.model,
            base_url=state.ollama_base_url,
        )
    )

    _render_history()
    _handle_input(
        service,
        repository.all()[state.prompt_key],
        state.settings,
        settings.max_input_length,
    )
