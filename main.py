from concurrent.futures import ThreadPoolExecutor, as_completed
import streamlit as st
from prompts_loader import DEFAULT_PROMPT, PROMPTS
import requests
import llm
import config

def render_reply(reply: str) -> None:
    if llm.is_not_interview_prep(reply):
        st.warning("This input does not look like a Job Posting.")
    st.markdown(reply)

def render_run_meta(result: dict) -> None:
    bits = []
    usage = result.get("usage") or {}

    if result.get("model"):
        bits.append(f"Model: {result['model']}")

    if result.get("latency_ms") is not None:
        bits.append(f"Latency: {result['latency_ms']}ms")

    total_tokens = usage.get("total_tokens")
    if total_tokens is not None:
        bits.append(f"Tokens: {total_tokens}")
    else:
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if prompt_tokens is not None and completion_tokens is not None:
            bits.append(f"Tokens: {prompt_tokens} in / {completion_tokens} out")

    cost = usage.get("cost")
    if cost is not None:
        bits.append(f"Cost: ${cost}")

    if bits:
        st.caption(" | ".join(bits))

def render_export_actions(result: dict, filename_prefix: str) -> None:
    st.download_button(
        "Download output",
        data=result["content"],
        file_name=f"{filename_prefix}.md",
        mime="text/markdown",
        key=f"download_{filename_prefix}",
    )

@st.cache_data(ttl=30)
def probe_ollama(base_url: str) -> dict:
    """Return {reachable: bool, models: list[str]} for an Ollama base URL."""
    try:
        response = requests.get(f"{base_url.rstrip('/')}/api/tags", timeout=config.OLLAMA_TIMEOUT)
        response.raise_for_status()
        models = [m["name"] for m in response.json().get("models", [])]
        return {"reachable": True, "models": models}
    except requests.exceptions.RequestException:
        return {"reachable": False, "models": []}

st.session_state.setdefault("last_user_input", None)
st.session_state.setdefault("last_mode", None)
st.session_state.setdefault("last_selected_key", None)
st.session_state.setdefault("last_results", None)

st.title("Kernector - Interview Analysis")

with st.sidebar:
    provider = st.radio(
        "Provider",
        ["openrouter", "ollama"],
        format_func=lambda p: "OpenRouter" if p == "openrouter" else "Ollama",
        index=0 if config.DEFAULT_PROVIDER == "openrouter" else 1,
    )

    selected_model = config.OPENROUTER_MODEL
    ollama_base_url = config.OLLAMA_BASE_URL

    if provider == "ollama":
        ollama_base_url = st.text_input("Ollama base URL", value=ollama_base_url)
        status = probe_ollama(ollama_base_url)
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
                "Ollama model",
                value=config.OLLAMA_MODEL,
            )
        elif not models:
            st.warning("Ollama is running, but no models are installed yet.")
            st.markdown("In a terminal, run: `ollama pull llama3.2`, then refresh.")
            selected_model = st.text_input(
                "Ollama model",
                value=config.OLLAMA_MODEL,
            )
        else:
            default_model = config.OLLAMA_MODEL or models[0]
            index = models.index(default_model) if default_model in models else 0
            selected_model = st.selectbox("Ollama model", options=models, index=index)
            st.caption("Ollama connected · local, slower, no API cost.")
    else:
        st.caption(f"OpenRouter model: {selected_model}")


    mode = st.radio("Mode", ["Single", "Compare"])
    selected_key = DEFAULT_PROMPT
    if mode == "Single":
        selected_key = st.selectbox(
            "Prompt variant",
            options=list(PROMPTS.keys()),
            format_func=lambda key: PROMPTS[key]["name"],
            index=list(PROMPTS.keys()).index(DEFAULT_PROMPT),
        )
        st.caption(PROMPTS[selected_key]["description"])
    elif provider == "ollama":
        st.caption(f"Compare will run {len(PROMPTS)} local calls and may be slow.")

user_input = st.chat_input("Paste a Job Posting to analyze")
if user_input:
    error = llm.validate_input(user_input)
    if error:
        st.error(error)
    else:
        st.session_state.last_user_input = user_input
        st.session_state.last_mode = mode
        st.session_state.last_selected_key = selected_key

        if mode == "Single":
            prompt = PROMPTS[selected_key]
            with st.spinner(f"Analyzing with {prompt['name']}..."):
                result = llm.ask(
                    prompt["system"],
                    user_input,
                    provider=provider,
                    model=selected_model,
                    ollama_base_url=ollama_base_url,
                )
            st.session_state.last_results = {selected_key: result}
        else:
            results = {}
            total = len(PROMPTS)
            progress_bar = st.progress(0.0)
            status = st.empty()
            status.write(f"Starting {total} compare runs...")
            with ThreadPoolExecutor() as executor:
                future_to_key = {
                    executor.submit(
                        llm.ask,
                        prompt["system"],
                        user_input,
                        provider,
                        selected_model,
                        ollama_base_url,
                    ): key
                    for key, prompt in PROMPTS.items()
                }
                for index, future in enumerate(as_completed(future_to_key), start=1):
                    key = future_to_key[future]
                    results[key] = future.result()
                    progress_bar.progress(index / total)
                    status.write(f"{index} of {total} variants complete")
                status.write("Compare run complete")

            st.session_state.last_results = results

if st.session_state.last_results and st.session_state.last_user_input:
    st.chat_message("user").write(st.session_state.last_user_input)

    if st.session_state.last_mode == "Single":
        key = st.session_state.last_selected_key
        result = st.session_state.last_results[key]
        with st.chat_message("assistant"):
            render_run_meta(result)
            render_reply(result["content"])
            render_export_actions(result, key)
    else:
        for key, prompt in PROMPTS.items():
            result = st.session_state.last_results[key]
            with st.expander(prompt["name"], expanded=True):
                st.caption(prompt["description"])
                render_run_meta(result)
                render_reply(result["content"])
                render_export_actions(result, key)
