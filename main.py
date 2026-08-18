import streamlit as st
from prompts_loader import DEFAULT_PROMPT, PROMPTS
import requests
import llm
import config
from model_settings import SETTINGS

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

    settings = result.get("settings") or {}
    if settings:
        bits.append(" · ".join(f"{k}={v}" for k, v in settings.items()))

    if bits:
        st.caption(" | ".join(bits))

def render_export_actions(content: str, filename_prefix: str) -> None:
    st.download_button(
        "Download output",
        data=content,
        file_name=f"{filename_prefix}.md",
        mime="text/markdown",
        key=f"download_{filename_prefix}",
    )

def render_model_settings(provider: str) -> dict:
    values = {}
    with st.expander("Model Settings", icon=":material/tune:"):
        st.caption("Defaults are safe. Change only what you need.")
        for setting in SETTINGS:
            if provider not in setting.providers:
                continue
            widget = st.slider if setting.widget == "slider" else st.number_input
            values[setting.key] = widget(
                setting.label,
                min_value=setting.min_value,
                max_value=setting.max_value,
                value=setting.default,
                step=setting.step,
                help=setting.help,
                key=f"setting_{provider}_{setting.key}",
            )
    return values

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

st.session_state.setdefault("messages", [])

st.title("Kernector - Interview Analysis")

with st.sidebar:
    provider = st.radio(
        "Provider",
        ["openrouter", "ollama"],
        format_func=lambda p: "OpenRouter" if p == "openrouter" else "Ollama",
        index=0 if config.DEFAULT_PROVIDER == "openrouter" else 1,
    )
    if st.button(
        "New chat",
        icon=":material/add_comment:",
        width="stretch",
        disabled=not st.session_state.messages,
    ):

        st.session_state.messages = []

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
        openrouter_models = config.OPENROUTER_MODELS
        if openrouter_models:
            default_model = config.OPENROUTER_MODEL or openrouter_models[0]
            index = (
                openrouter_models.index(default_model)
                if default_model in openrouter_models
                else 0
            )
            selected_model = st.selectbox("OpenRouter model", options=openrouter_models, index=index)
        else:
            selected_model = st.text_input(
                "OpenRouter model",
                value=config.OPENROUTER_MODEL
                )
            st.caption("No OpenRouter models available")

    model_config = render_model_settings(provider)

    selected_key = st.selectbox(
        "Prompt variant",
        options=list(PROMPTS.keys()),
        format_func=lambda key: PROMPTS[key]["name"],
        index=list(PROMPTS.keys()).index(DEFAULT_PROMPT),
    )
    st.caption(PROMPTS[selected_key]["description"])
    
for  index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        if message["role"] == "assistant":
            render_run_meta(message.get("meta") or {})
            render_reply(message["content"])
            render_export_actions(message["content"], f"analysis_{index}")
        else:
            st.markdown(message["content"])

user_input = st.chat_input("Paste a Job Posting to analyze")
if user_input:
    error = llm.validate_input(user_input)
    if error:
        st.error(error)
    else:
        history = list(st.session_state.messages)
        st.session_state.messages.append({"role": "user", "content": user_input})

        with st.chat_message("user"):
            st.markdown(user_input)

        prompt = PROMPTS[selected_key]
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                result = llm.ask(
                    prompt["system"],
                    user_input,
                    provider=provider,
                    model=selected_model,
                    ollama_base_url=ollama_base_url,
                    model_config=model_config,
                    history=history,
                )
            render_run_meta(result)
            render_reply(result["content"])
            render_export_actions(result["content"], f"analysis_{len(st.session_state.messages)}")

        st.session_state.messages.append({
            "role": "assistant",
            "content": result["content"],
            "meta": {
                "model": result["model"],
                "latency_ms": result["latency_ms"],
                "usage": result["usage"],
                "settings": result["settings"],
            },
        })
