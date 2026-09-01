"""Streamlit app: page flow."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import streamlit as st

from application.contracts import Citation, InvokeToolResponse
from application.errors import ConfigurationError
from composition import (
    GroundedAsk,
    RequirementsAnalysisFindingView,
    SUPPORTED_UPLOAD_SUFFIXES,
    Settings,
    available_providers,
    build_analyze_requirements,
    build_chat_model,
    build_prompt_repository,
    build_tool_augmented_ask,
    load_runtime_settings,
    probe_ollama,
    requirements_analysis_enabled,
)
from domain.models import Message
from domain.ports import ChatModel, PromptRepository
from presentation.streamlit.analysis_turn import (
    AnalysisContext,
    StoredAnalysisResult,
    analysis_result_after_successful_document_mutation,
    analysis_result_for_display,
    finding_bullets,
    run_analysis_turn,
)
from presentation.streamlit.ask_turn import run_ask_turn, tool_output_lines
from presentation.streamlit.components import (
    render_export_actions,
    render_model_settings,
    render_reply,
    render_run_meta,
)
from presentation.streamlit.modes import default_mode_index, mode_options
from presentation.streamlit.upload_ingest import (
    UploadIngestResult,
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
    prompt_key: str | None


@st.cache_resource
def _settings() -> Settings:
    return load_runtime_settings()


@st.cache_resource
def _prompt_repository() -> PromptRepository:
    return build_prompt_repository(_settings())


@st.cache_data(ttl=30)
def _cached_probe(_settings: Settings, base_url: str) -> dict:
    return probe_ollama(_settings, base_url)


def _render_citations(citations: Sequence[Citation]) -> None:
    if not citations:
        return
    with st.expander(f"Citations ({len(citations)})"):
        for index, citation in enumerate(citations, start=1):
            ref = citation.reference
            st.markdown(
                f"**{index}.** `{ref.source_id}` ({ref.source_type})"
                + (f" · chunk {citation.chunk_index}" if citation.chunk_index is not None else "")
            )
            if citation.quote:
                st.caption(citation.quote)


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
        st.session_state.pop(_ANALYSIS_RESULT_KEY, None)

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

    # The (key, label) pairs are the options themselves. Mapping `None` onto a
    # blank-string sentinel would collide with a pack whose frontmatter `key:`
    # is empty — nothing validates that — and the collision silently turns
    # General into that pack's prompt.
    options = mode_options(prompts)
    selected_option = st.selectbox(
        "Mode",
        options=options,
        format_func=lambda option: option[1],
        index=default_mode_index(options),
    )
    prompt_key = selected_option[0]
    if prompt_key is None:
        st.caption("General grounded chat over ingested documents.")
    else:
        st.caption(prompts[prompt_key].description)

    return _SidebarState(
        provider=provider,
        model=selected_model,
        ollama_base_url=ollama_base_url,
        settings=settings_values,
        prompt_key=prompt_key,
    )


def _render_tool_outputs(tool_outputs: Sequence[InvokeToolResponse]) -> None:
    """Name the tools a turn ran. The payload stays opaque, as its contract says.

    Structured rendering of a pack's results is a pack-specific projection, and
    this module may not name a pack. What belongs here is the fact that tools
    ran at all — the answer itself already carries what they produced.
    """
    if not tool_outputs:
        return
    with st.expander(f"Tools used ({len(tool_outputs)})"):
        for line in tool_output_lines(tool_outputs):
            st.markdown(line)


def _render_history() -> None:
    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                render_run_meta(message.get("run"))
                render_reply(message["content"], message.get("off_topic_marker"))
                _render_citations(message.get("citations") or ())
                _render_tool_outputs(message.get("tool_outputs") or ())
                render_export_actions(message["content"], f"analysis_{index}")
            else:
                st.markdown(message["content"])


def _handle_input(
    ask: GroundedAsk,
    prompt_key: str | None,
    settings: Mapping[str, object],
    off_topic_marker: str | None,
) -> None:
    user_input = st.chat_input("Start typing...")
    if not user_input:
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
            result = run_ask_turn(
                ask,
                query=user_input,
                prompt_key=prompt_key,
                history=history,
                settings=settings,
            )
            if not result.ok:
                # A rejected turn must not persist. `history` is rebuilt from
                # session state on the next submit and handed to the model, so
                # keeping it would ship the exact text the boundary refused.
                # The bubble drawn above disappears on the next rerun.
                if result.drop_user_turn:
                    st.session_state.messages.pop()
                st.error(result.message)
                return
            response = result.response
            assert response is not None
        render_run_meta(response.run)
        render_reply(response.answer, off_topic_marker)
        _render_citations(response.citations)
        _render_tool_outputs(response.tool_outputs)
        render_export_actions(
            response.answer, f"analysis_{len(st.session_state.messages)}"
        )

    st.session_state.messages.append({
        "role": "assistant",
        "content": response.answer,
        "citations": response.citations,
        "tool_outputs": response.tool_outputs,
        "run": response.run,
        "off_topic_marker": off_topic_marker,
    })


_ACTION_MESSAGE_KEY = "document_action_message"
_ANALYSIS_RESULT_KEY = "requirements_analysis_result"


def _render_findings(
    title: str, findings: Sequence[RequirementsAnalysisFindingView]
) -> None:
    if not findings:
        return
    st.markdown(f"**{title}**")
    for bullet in finding_bullets(findings):
        st.markdown(bullet)


def _render_requirements_analysis(
    settings: Settings,
    chat_model: ChatModel,
    *,
    provider: str,
    model: str,
) -> None:
    """Analyze pasted requirements. Absent unless the domain pack is enabled."""
    if not requirements_analysis_enabled(settings):
        return

    try:
        analyzer = build_analyze_requirements(settings, chat_model=chat_model)
    except ConfigurationError as error:
        st.error(str(error))
        return

    st.subheader("Requirements analysis")
    with st.form("requirements_analysis"):
        requirements = st.text_area(
            "Requirements",
            height=180,
            help="Paste a story or requirements text. Analysis is grounded in "
            "ingested documents across every source kind.",
        )
        submitted = st.form_submit_button("Analyze")

    context = AnalysisContext(
        requirements=requirements,
        provider=provider,
        model=model,
    )

    if submitted:
        with st.spinner("Analyzing..."):
            st.session_state[_ANALYSIS_RESULT_KEY] = StoredAnalysisResult(
                context=context,
                result=run_analysis_turn(analyzer, requirements=requirements),
            )

    stored = st.session_state.get(_ANALYSIS_RESULT_KEY)
    result = analysis_result_for_display(stored, context=context)
    if result is None:
        return
    if not result.ok:
        st.error(result.message)
        return

    assert result.view is not None
    st.markdown(result.view.summary)
    _render_findings("Acceptance criteria gaps", result.view.acceptance_criteria_gaps)
    _render_findings("Risks", result.view.risks)
    _render_findings("Clarification questions", result.view.clarification_questions)
    _render_citations(result.citations)


def _apply_action_result(result: UploadIngestResult) -> None:
    """Show one action's outcome, surviving the rerun that follows a success.

    ``st.rerun`` aborts the current script run, and the frontend drops the
    elements that run had already written — so a success banner rendered just
    before it never reaches the reader. The message is parked in session state
    instead and drawn at the top of the next run.
    """
    if not result.ok:
        st.error(result.message)
        return
    st.session_state[_ANALYSIS_RESULT_KEY] = (
        analysis_result_after_successful_document_mutation(
            st.session_state.get(_ANALYSIS_RESULT_KEY)
        )
    )
    if result.should_rerun:
        st.session_state[_ACTION_MESSAGE_KEY] = result.message
        st.rerun()  # Raises; nothing after this line runs.
        return
    st.success(result.message)


def _render_upload_ingest(settings: Settings) -> None:
    """List uploaded documents and support create, explicit replace, and delete."""
    st.subheader("Uploaded documents")
    completed = st.session_state.pop(_ACTION_MESSAGE_KEY, None)
    if completed:
        st.success(completed)

    listing = load_uploaded_documents(settings)
    if listing.error:
        st.error(listing.error)
    documents = list(listing.documents)

    selected = None
    if documents:
        labels = {
            f"{doc.file_name} · {doc.status.value} · {doc.reference.source_id}": doc
            for doc in documents
        }
        selected_label = st.selectbox(
            "Managed documents",
            options=list(labels.keys()),
            help="Catalog identity is the source ID, not the file name. Matching "
            "names stay separate documents until you explicitly Replace.",
        )
        selected = labels[selected_label]
        st.caption(
            f"Status: {selected.status.value} · chunks: {selected.chunk_count} · "
            f"uploaded: {selected.uploaded_at.isoformat()}"
        )
        if selected.error:
            st.warning(selected.error)
    else:
        st.caption(
            "No uploaded documents yet. Seed-corpus documents are managed separately "
            "and do not appear here."
        )

    action_options = ["Upload new"]
    if selected is not None:
        action_options.extend(["Replace selected", "Delete selected"])
    action = st.radio(
        "Document action",
        options=action_options,
        horizontal=True,
        help="Upload new always creates a new source ID. Replace only runs when "
        "you choose Replace selected — the app never treats a matching file name "
        "as the same document.",
    )

    if action == "Upload new":
        st.caption("A system-managed source ID is assigned automatically.")
        with st.form("document_upload_new"):
            uploaded = st.file_uploader(
                "Document",
                type=sorted(
                    suffix.lstrip(".") for suffix in SUPPORTED_UPLOAD_SUFFIXES
                ),
                accept_multiple_files=False,
                key="upload_new_file",
            )
            submitted_new = st.form_submit_button("Upload new")
        if submitted_new:
            _apply_action_result(
                create_new_document(
                    settings,
                    filename=uploaded.name if uploaded is not None else None,
                    content=uploaded.getvalue() if uploaded is not None else None,
                )
            )
        return

    if selected is None:
        return

    if action == "Replace selected":
        st.caption(
            f"Keeps source ID {selected.reference.source_id} and replaces "
            "stored chunks. File name is ignored for identity."
        )
        with st.form("document_upload_replace"):
            replacement = st.file_uploader(
                "Replacement document",
                type=sorted(
                    suffix.lstrip(".") for suffix in SUPPORTED_UPLOAD_SUFFIXES
                ),
                accept_multiple_files=False,
                key="upload_replace_file",
            )
            submitted_replace = st.form_submit_button("Replace")
        if submitted_replace:
            _apply_action_result(
                replace_existing_document(
                    settings,
                    reference=selected.reference,
                    filename=replacement.name if replacement is not None else None,
                    content=(
                        replacement.getvalue() if replacement is not None else None
                    ),
                )
            )
        return

    st.caption(
        f"Removes catalog row and vector chunks for {selected.file_name} "
        f"({selected.reference.source_id})."
    )
    confirm = st.checkbox(
        f"Confirm delete of {selected.file_name}",
        key=f"confirm_delete_{selected.reference.source_id}",
    )
    if st.button("Delete", disabled=not confirm):
        _apply_action_result(
            delete_existing_document(settings, reference=selected.reference)
        )


def render() -> None:
    st.session_state.setdefault("messages", [])

    settings = _settings()
    repository = _prompt_repository()

    st.title("Kernector")

    with st.sidebar:
        state = _render_sidebar(settings, repository)

    _render_upload_ingest(settings)

    try:
        chat_model = build_chat_model(
            settings,
            provider=state.provider,
            model=state.model,
            base_url=state.ollama_base_url,
        )
        ask = build_tool_augmented_ask(
            settings,
            chat_model=chat_model,
            prompt_repository=repository,
        )
    except ConfigurationError as error:
        st.error(str(error))
        return

    _render_requirements_analysis(
        settings,
        chat_model,
        provider=state.provider,
        model=state.model,
    )

    prompts = repository.all()
    off_topic_marker = (
        prompts[state.prompt_key].off_topic_marker
        if state.prompt_key is not None
        else None
    )

    _render_history()
    _handle_input(
        ask,
        state.prompt_key,
        state.settings,
        off_topic_marker,
    )
